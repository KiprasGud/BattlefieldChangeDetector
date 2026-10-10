"""Batch review records: one batch per name-paired source pair, its matched frame pairs, and their findings with
the reviewer's verdict. Same SQLite file as the job history, but never pruned automatically: reviews must survive."""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..contracts import Change
from .db import get_connection

REVIEW_STATUSES = ("pending", "accepted", "rejected")
ACTIVE_STATUSES = ("queued", "running", "done")

_BATCH_COLUMNS = {
    "site", "name_a", "name_b", "tag_a", "tag_b", "path_a", "path_b", "kind_a", "kind_b", "signature",
    "ai_enabled", "status", "stage", "progress", "frames_a", "frames_b", "matched_pairs", "pairs_count",
    "error_message",
}
_JSON_COLUMNS = {"timings": "timings_json", "warnings": "warnings_json"}

_COUNTS = """
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id) AS findings_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'pending') AS pending_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'accepted') AS accepted_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'rejected') AS rejected_count
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _db():
    conn = get_connection()
    try:
        with conn:  # commits, or rolls back on error
            yield conn
    finally:
        conn.close()


def init_batch_db() -> None:
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                created_at TEXT,
                updated_at TEXT,
                site TEXT,              -- naming key, e.g. 'Site_A'
                name_a TEXT, name_b TEXT, tag_a TEXT, tag_b TEXT,
                path_a TEXT, path_b TEXT,
                kind_a TEXT, kind_b TEXT,   -- 'image' | 'video', from file content
                signature TEXT,         -- sha256 of both content hashes: same media is not processed twice
                ai_enabled INTEGER,
                status TEXT,            -- 'queued', 'running', 'done', 'error'
                stage TEXT,             -- 'queued', 'extracting', 'matching', 'comparing', 'done', 'error'
                progress TEXT,          -- e.g. '3/12' while comparing pairs
                frames_a INTEGER, frames_b INTEGER,
                matched_pairs INTEGER,  -- curated frame pairs that show the same ground
                pairs_count INTEGER,    -- matched pairs with at least one finding
                timings_json TEXT,
                warnings_json TEXT,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_batches_created ON batches(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_batches_signature ON batches(signature);

            CREATE TABLE IF NOT EXISTS frame_pairs (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                idx INTEGER,            -- 1-based, also the folder name pair_NN
                frame_a INTEGER, frame_b INTEGER,
                time_a REAL, time_b REAL,
                inliers INTEGER, overlap REAL, ssim REAL,
                align_quality REAL, align_method TEXT,
                change_ratio REAL,      -- share of covered pixels the heatmap marks as changed
                source TEXT,            -- 'ai' | 'cv': who produced the findings
                summary TEXT, recommendation TEXT,
                images_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pairs_batch ON frame_pairs(batch_id, idx);

            CREATE TABLE IF NOT EXISTS findings (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                pair_id TEXT,
                idx INTEGER,
                category TEXT, type TEXT, description TEXT, location_text TEXT, confidence TEXT,
                box_json TEXT,          -- [ymin, xmin, ymax, xmax] 0-1000 in the A frame
                sector TEXT,
                review_status TEXT DEFAULT 'pending',
                reviewed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_findings_pair ON findings(pair_id, idx);
            CREATE INDEX IF NOT EXISTS idx_findings_batch ON findings(batch_id);
            """
        )


def create_batch(batch_id: str, **fields: Any) -> None:
    now = _now()
    values = {k: v for k, v in fields.items() if k in _BATCH_COLUMNS}
    values.update(status="queued", stage="queued", progress="", timings_json="{}", warnings_json="[]")
    values["ai_enabled"] = 1 if values.get("ai_enabled") else 0
    cols = ["id", "created_at", "updated_at", *values]
    with _db() as conn:
        conn.execute(
            f"INSERT INTO batches ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            (batch_id, now, now, *values.values()),
        )


def update_batch(batch_id: str, **fields: Any) -> None:
    sets: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _JSON_COLUMNS:
            sets[_JSON_COLUMNS[key]] = json.dumps(value)
        elif key in _BATCH_COLUMNS:
            sets[key] = value
    sets["updated_at"] = _now()
    with _db() as conn:
        conn.execute(
            f"UPDATE batches SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
            (*sets.values(), batch_id),
        )


def finish_batch(batch_id: str, pairs_count: int, timings: dict, warnings: list[str]) -> None:
    update_batch(batch_id, status="done", stage="done", progress="", pairs_count=pairs_count,
                 timings=timings, warnings=warnings)


def fail_batch(batch_id: str, message: str, warnings: Optional[list[str]] = None) -> None:
    update_batch(batch_id, status="error", stage="error", progress="", error_message=message[:500],
                 warnings=warnings or [])


def find_active_batch(signature: str) -> Optional[str]:
    """A queued, running or finished batch for the same content pair (failed ones may be retried)."""
    with _db() as conn:
        row = conn.execute(
            f"SELECT id FROM batches WHERE signature = ? AND status IN ({', '.join('?' * len(ACTIVE_STATUSES))}) "
            "ORDER BY created_at DESC LIMIT 1",
            (signature, *ACTIVE_STATUSES),
        ).fetchone()
    return row["id"] if row else None


def reset_interrupted() -> list[str]:
    """Batches left queued or running by a stopped process go back to the queue; returns their ids."""
    with _db() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM batches WHERE status IN ('queued', 'running') ORDER BY created_at"
        ).fetchall()]
        conn.execute("UPDATE batches SET status = 'queued', stage = 'queued', progress = '' "
                     "WHERE status IN ('queued', 'running')")
    return ids


def clear_pairs(batch_id: str) -> None:
    with _db() as conn:
        conn.execute("DELETE FROM findings WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM frame_pairs WHERE batch_id = ?", (batch_id,))


def add_pair(batch_id: str, pair: dict[str, Any], changes: Iterable[Change]) -> str:
    """Store one compared frame pair and its findings (all pending review); returns the pair id."""
    pair_id = uuid.uuid4().hex[:12]
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO frame_pairs (id, batch_id, idx, frame_a, frame_b, time_a, time_b, inliers, overlap, ssim,
                                     align_quality, align_method, change_ratio, source, summary, recommendation,
                                     images_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pair_id, batch_id, pair["idx"], pair["frame_a"], pair["frame_b"], pair["time_a"], pair["time_b"],
                pair["inliers"], pair["overlap"], pair["ssim"], pair["align_quality"], pair["align_method"],
                pair["change_ratio"], pair["source"], pair.get("summary", ""), pair.get("recommendation", ""),
                json.dumps(pair["images"]),
            ),
        )
        for i, c in enumerate(changes, 1):
            conn.execute(
                """
                INSERT INTO findings (id, batch_id, pair_id, idx, category, type, description, location_text,
                                      confidence, box_json, sector, review_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    uuid.uuid4().hex[:12], batch_id, pair_id, i, c.category or "unknown_anomaly", c.type,
                    c.description, c.location_text, c.confidence, json.dumps(c.box), c.sector,
                ),
            )
    return pair_id


def set_review(finding_id: str, status: str) -> Optional[dict[str, Any]]:
    if status not in REVIEW_STATUSES:
        raise ValueError(f"status must be one of {REVIEW_STATUSES}")
    with _db() as conn:
        cur = conn.execute(
            "UPDATE findings SET review_status = ?, reviewed_at = ? WHERE id = ?",
            (status, _now() if status != "pending" else None, finding_id),
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    return _finding(row)


def get_batch(batch_id: str) -> Optional[dict[str, Any]]:
    with _db() as conn:
        row = conn.execute(f"SELECT b.*, {_COUNTS} FROM batches b WHERE b.id = ?", (batch_id,)).fetchone()
    return _batch(row) if row else None


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute(
            f"SELECT b.*, {_COUNTS} FROM batches b ORDER BY b.created_at DESC, b.rowid DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_batch(r) for r in rows]


def batch_detail(batch_id: str) -> Optional[dict[str, Any]]:
    """The batch with its frame pairs (by idx), each with its findings (by idx)."""
    batch = get_batch(batch_id)
    if batch is None:
        return None
    with _db() as conn:
        pairs = [dict(r) for r in conn.execute(
            "SELECT * FROM frame_pairs WHERE batch_id = ? ORDER BY idx", (batch_id,)
        ).fetchall()]
        findings = [_finding(r) for r in conn.execute(
            "SELECT * FROM findings WHERE batch_id = ? ORDER BY idx", (batch_id,)
        ).fetchall()]
    by_pair: dict[str, list] = {}
    for f in findings:
        by_pair.setdefault(f["pair_id"], []).append(f)
    for p in pairs:
        p["images"] = json.loads(p.pop("images_json") or "{}")
        p["findings"] = by_pair.get(p["id"], [])
    batch["pairs"] = pairs
    return batch


def _batch(row) -> dict[str, Any]:
    d = dict(row)
    d["ai_enabled"] = bool(d.get("ai_enabled"))
    d["timings"] = json.loads(d.pop("timings_json") or "{}")
    d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
    return d


def _finding(row) -> dict[str, Any]:
    d = dict(row)
    d["box"] = json.loads(d.pop("box_json") or "[0, 0, 0, 0]")
    return d
