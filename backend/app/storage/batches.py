"""Batch review records: one batch per project (all epochs of one naming key), its legs (consecutive epoch pairs:
Day1 -> Day2, Day2 -> Day5), their matched frame pairs, and the findings with the reviewer's verdict. Same SQLite file
as the job history, but never pruned automatically: reviews must survive."""
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from ..contracts import Change
from .db import get_connection

REVIEW_STATUSES = ("pending", "accepted", "rejected")

_BATCH_COLUMNS = {
    "site", "project", "name_a", "name_b", "tag_a", "tag_b", "path_a", "path_b", "kind_a", "kind_b", "signature",
    "ai_enabled", "status", "stage", "progress", "frames_a", "frames_b", "matched_pairs", "pairs_count",
    "error_message",
}
_LEG_COLUMNS = {
    "tag_a", "tag_b", "name_a", "name_b", "path_a", "path_b", "kind_a", "kind_b", "signature", "status",
    "frames_a", "frames_b", "matched_pairs", "error_message",
}
_JSON_COLUMNS = {"timings": "timings_json", "warnings": "warnings_json"}

_COUNTS = """
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id) AS findings_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'pending') AS pending_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'accepted') AS accepted_count,
    (SELECT COUNT(*) FROM findings f WHERE f.batch_id = b.id AND f.review_status = 'rejected') AS rejected_count,
    (SELECT COUNT(*) FROM batch_legs l WHERE l.batch_id = b.id) AS legs_count
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
                project TEXT,           -- grouping key: the site, case-folded
                name_a TEXT, name_b TEXT, tag_a TEXT, tag_b TEXT,   -- *_a: first epoch, *_b: latest epoch
                path_a TEXT, path_b TEXT,
                kind_a TEXT, kind_b TEXT,   -- 'image' | 'video', from file content
                signature TEXT,
                ai_enabled INTEGER,
                status TEXT,            -- 'queued', 'running', 'done', 'error'
                stage TEXT,             -- 'queued', 'extracting', 'matching', 'comparing', 'done', 'error'
                progress TEXT,          -- e.g. 'Day1→Day2 3/12' while comparing pairs
                frames_a INTEGER, frames_b INTEGER,
                matched_pairs INTEGER,  -- curated frame pairs that show the same ground, all legs
                pairs_count INTEGER,    -- matched pairs with at least one finding, all legs
                timings_json TEXT,
                warnings_json TEXT,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_batches_created ON batches(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_batches_signature ON batches(signature);

            CREATE TABLE IF NOT EXISTS batch_legs (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                idx INTEGER,            -- 1-based, in the order the legs were added
                tag_a TEXT, tag_b TEXT, name_a TEXT, name_b TEXT, path_a TEXT, path_b TEXT,
                kind_a TEXT, kind_b TEXT,
                signature TEXT,         -- sha256 of both content hashes: same media is not processed twice
                status TEXT,            -- 'pending', 'running', 'done', 'error'
                frames_a INTEGER, frames_b INTEGER, matched_pairs INTEGER,
                timings_json TEXT,
                warnings_json TEXT,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_legs_batch ON batch_legs(batch_id, idx);

            CREATE TABLE IF NOT EXISTS frame_pairs (
                id TEXT PRIMARY KEY,
                batch_id TEXT,
                leg_idx INTEGER,        -- the batch leg this pair belongs to
                idx INTEGER,            -- 1-based across the whole batch, also the folder name pair_NN
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
        _migrate(conn)


def _migrate(conn) -> None:
    """Databases from before project batches: add the new columns and give every old batch its one leg."""
    for table, column, kind in (("batches", "project", "TEXT"), ("frame_pairs", "leg_idx", "INTEGER")):
        if column not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.execute("UPDATE batches SET project = lower(site) WHERE project IS NULL")
    conn.execute("UPDATE frame_pairs SET leg_idx = 1 WHERE leg_idx IS NULL")
    for b in conn.execute(
        "SELECT * FROM batches b WHERE NOT EXISTS (SELECT 1 FROM batch_legs l WHERE l.batch_id = b.id)"
    ).fetchall():
        conn.execute(
            """
            INSERT INTO batch_legs (id, batch_id, idx, tag_a, tag_b, name_a, name_b, path_a, path_b, kind_a, kind_b,
                                    signature, status, frames_a, frames_b, matched_pairs, timings_json, warnings_json,
                                    error_message)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (uuid.uuid4().hex[:12], b["id"], b["tag_a"], b["tag_b"], b["name_a"], b["name_b"], b["path_a"],
             b["path_b"], b["kind_a"], b["kind_b"], b["signature"],
             b["status"] if b["status"] in ("done", "error") else "pending", b["frames_a"], b["frames_b"],
             b["matched_pairs"], b["timings_json"] or "{}", b["warnings_json"] or "[]", b["error_message"]),
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


def finish_batch(batch_id: str, pairs_count: int, timings: dict, warnings: list[str], **fields: Any) -> None:
    update_batch(batch_id, status="done", stage="done", progress="", pairs_count=pairs_count,
                 timings=timings, warnings=warnings, error_message=None, **fields)


def fail_batch(batch_id: str, message: str, warnings: Optional[list[str]] = None) -> None:
    update_batch(batch_id, status="error", stage="error", progress="", error_message=message[:500],
                 warnings=warnings or [])


def find_project_batch(project: str) -> Optional[dict[str, Any]]:
    """The project's latest batch: new epochs of the project are added to it as legs."""
    with _db() as conn:
        row = conn.execute(
            f"SELECT b.*, {_COUNTS} FROM batches b WHERE b.project = ? ORDER BY b.created_at DESC, b.rowid DESC LIMIT 1",
            (project,),
        ).fetchone()
    return _batch(row) if row else None


def project_legs() -> dict[str, set[tuple[str, str]]]:
    """(name_a, name_b) of every leg that has not failed, by project: which inbox pairs are already batched."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT b.project, l.name_a, l.name_b FROM batch_legs l JOIN batches b ON b.id = l.batch_id "
            "WHERE l.status != 'error'"
        ).fetchall()
    out: dict[str, set[tuple[str, str]]] = {}
    for r in rows:
        out.setdefault(r["project"], set()).add((r["name_a"], r["name_b"]))
    return out


def reset_interrupted() -> list[str]:
    """Batches left queued or running by a stopped process go back to the queue; returns their ids."""
    with _db() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM batches WHERE status IN ('queued', 'running') ORDER BY created_at"
        ).fetchall()]
        conn.execute("UPDATE batches SET status = 'queued', stage = 'queued', progress = '' "
                     "WHERE status IN ('queued', 'running')")
        conn.execute("UPDATE batch_legs SET status = 'pending' WHERE status = 'running'")
    return ids


def queued_count() -> int:
    with _db() as conn:
        return conn.execute("SELECT COUNT(*) FROM batches WHERE status = 'queued'").fetchone()[0]


def clear_queued() -> dict[str, list]:
    """Flush the queue; the running batch is left alone. A queued batch with no finished leg is deleted. One that a
    new epoch re-opened loses only its unfinished legs and goes back to 'done', so finished reviews survive.
    Returns the deleted batch ids, the dropped pair folders as (batch id, pair idx), and the source file names."""
    deleted: list[str] = []
    dropped: list[tuple[str, int]] = []
    files: set[str] = set()
    with _db() as conn:
        for b in conn.execute("SELECT id FROM batches WHERE status = 'queued'").fetchall():
            legs = conn.execute("SELECT * FROM batch_legs WHERE batch_id = ?", (b["id"],)).fetchall()
            done = [leg for leg in legs if leg["status"] == "done"]
            for leg in legs:
                if leg["status"] == "done":
                    continue
                files.update((leg["name_a"], leg["name_b"]))
                for p in conn.execute("SELECT id, idx FROM frame_pairs WHERE batch_id = ? AND leg_idx = ?",
                                      (b["id"], leg["idx"])).fetchall():
                    dropped.append((b["id"], p["idx"]))
                    conn.execute("DELETE FROM findings WHERE pair_id = ?", (p["id"],))
                conn.execute("DELETE FROM frame_pairs WHERE batch_id = ? AND leg_idx = ?", (b["id"], leg["idx"]))
                conn.execute("DELETE FROM batch_legs WHERE id = ?", (leg["id"],))
            if done:
                last = max(done, key=lambda leg: leg["idx"])
                conn.execute(
                    "UPDATE batches SET status = 'done', stage = 'done', progress = '', tag_b = ?, name_b = ?, "
                    "path_b = ?, updated_at = ? WHERE id = ?",
                    (last["tag_b"], last["name_b"], last["path_b"], _now(), b["id"]),
                )
            else:
                conn.execute("DELETE FROM batches WHERE id = ?", (b["id"],))
                deleted.append(b["id"])
    return {"deleted": deleted, "dropped_pairs": dropped, "files": sorted(files)}


# --- legs -------------------------------------------------------------------------------------------

def add_leg(batch_id: str, **fields: Any) -> str:
    leg_id = uuid.uuid4().hex[:12]
    values = {k: v for k, v in fields.items() if k in _LEG_COLUMNS}
    values.setdefault("status", "pending")
    with _db() as conn:
        idx = conn.execute(
            "SELECT COALESCE(MAX(idx), 0) + 1 FROM batch_legs WHERE batch_id = ?", (batch_id,)
        ).fetchone()[0]
        cols = ["id", "batch_id", "idx", "timings_json", "warnings_json", *values]
        conn.execute(
            f"INSERT INTO batch_legs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            (leg_id, batch_id, idx, "{}", "[]", *values.values()),
        )
    return leg_id


def update_leg(leg_id: str, **fields: Any) -> None:
    sets: dict[str, Any] = {}
    for key, value in fields.items():
        if key in _JSON_COLUMNS:
            sets[_JSON_COLUMNS[key]] = json.dumps(value)
        elif key in _LEG_COLUMNS:
            sets[key] = value
    if sets:
        with _db() as conn:
            conn.execute(f"UPDATE batch_legs SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
                         (*sets.values(), leg_id))


def list_legs(batch_id: str) -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM batch_legs WHERE batch_id = ? ORDER BY idx", (batch_id,)).fetchall()
    return [_leg(r) for r in rows]


def next_pending_leg(batch_id: str) -> Optional[dict[str, Any]]:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM batch_legs WHERE batch_id = ? AND status = 'pending' ORDER BY idx LIMIT 1", (batch_id,)
        ).fetchone()
    return _leg(row) if row else None


def next_pair_idx(batch_id: str) -> int:
    with _db() as conn:
        return conn.execute(
            "SELECT COALESCE(MAX(idx), 0) + 1 FROM frame_pairs WHERE batch_id = ?", (batch_id,)
        ).fetchone()[0]


def clear_leg_pairs(batch_id: str, leg_idx: int) -> list[int]:
    """Drop a leg's frame pairs and findings (a retried leg starts clean); returns the dropped pair idxs."""
    with _db() as conn:
        pairs = conn.execute(
            "SELECT id, idx FROM frame_pairs WHERE batch_id = ? AND leg_idx = ?", (batch_id, leg_idx)
        ).fetchall()
        for p in pairs:
            conn.execute("DELETE FROM findings WHERE pair_id = ?", (p["id"],))
        conn.execute("DELETE FROM frame_pairs WHERE batch_id = ? AND leg_idx = ?", (batch_id, leg_idx))
    return [p["idx"] for p in pairs]


def add_pair(batch_id: str, pair: dict[str, Any], changes: Iterable[Change]) -> str:
    """Store one compared frame pair and its findings (all pending review); returns the pair id."""
    pair_id = uuid.uuid4().hex[:12]
    with _db() as conn:
        conn.execute(
            """
            INSERT INTO frame_pairs (id, batch_id, leg_idx, idx, frame_a, frame_b, time_a, time_b, inliers, overlap,
                                     ssim, align_quality, align_method, change_ratio, source, summary, recommendation,
                                     images_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pair_id, batch_id, pair.get("leg_idx", 1), pair["idx"], pair["frame_a"], pair["frame_b"],
                pair["time_a"], pair["time_b"], pair["inliers"], pair["overlap"], pair["ssim"], pair["align_quality"],
                pair["align_method"], pair["change_ratio"], pair["source"], pair.get("summary", ""),
                pair.get("recommendation", ""), json.dumps(pair["images"]),
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
    """The batch with its legs and frame pairs (by idx); each pair carries its leg's epochs and its findings."""
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
    legs = list_legs(batch_id)
    by_leg = {leg["idx"]: leg for leg in legs}
    by_pair: dict[str, list] = {}
    for f in findings:
        by_pair.setdefault(f["pair_id"], []).append(f)
    for p in pairs:
        leg = by_leg.get(p["leg_idx"], {})
        p.update({k: leg.get(k) for k in ("tag_a", "tag_b", "kind_a", "kind_b")})
        p["images"] = json.loads(p.pop("images_json") or "{}")
        p["findings"] = by_pair.get(p["id"], [])
    batch["legs"] = legs
    batch["pairs"] = pairs
    return batch


def _batch(row) -> dict[str, Any]:
    d = dict(row)
    d["ai_enabled"] = bool(d.get("ai_enabled"))
    d["timings"] = json.loads(d.pop("timings_json") or "{}")
    d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
    return d


def _leg(row) -> dict[str, Any]:
    d = dict(row)
    d["timings"] = json.loads(d.pop("timings_json") or "{}")
    d["warnings"] = json.loads(d.pop("warnings_json") or "[]")
    return d


def _finding(row) -> dict[str, Any]:
    d = dict(row)
    d["box"] = json.loads(d.pop("box_json") or "[0, 0, 0, 0]")
    return d
