"""PERSON 3: SQLite database for mission history, stage updates, and disk pruning."""
import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

DB_DIR = Path(__file__).resolve().parents[2] / "output"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "zvalgas.db"

# Job columns stored as JSON: (key in the returned dict, column, value used while the column is empty).
_JSON_FIELDS = (
    ("result", "result_json", "null"),
    ("timings", "timings_json", "{}"),
    ("warnings", "warnings_json", "[]"),
    ("images", "images_json", "{}"),
)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits on success, rolls back on error, and is always closed."""
    conn = get_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def _utcnow() -> str:
    """Naive UTC ISO timestamp, the format every stored job uses (datetime.utcnow() is deprecated)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT,          -- 'queued', 'running', 'done', 'error'
                stage TEXT,           -- 'queued', 'aligning', 'heatmap', 'ai', 'render', 'done', 'error'
                criteria TEXT,
                lang TEXT,
                align_quality REAL,
                align_ok INTEGER,
                align_method TEXT,
                changes_count INTEGER,
                summary TEXT,
                result_json TEXT,
                timings_json TEXT,
                warnings_json TEXT,
                images_json TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC)")


def create_job(job_id: str, criteria: str, lang: str = "en") -> dict[str, Any]:
    init_db()
    now = _utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, created_at, updated_at, status, stage, criteria, lang, timings_json, warnings_json)
            VALUES (?, ?, ?, 'queued', 'queued', ?, ?, '{}', '[]')
            """,
            (job_id, now, now, criteria, lang),
        )
    return {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "created_at": now,
        "criteria": criteria,
        "lang": lang,
        "timings": {},
        "warnings": [],
    }


def update_job_stage(job_id: str, stage: str, timings: Optional[dict[str, float]] = None) -> None:
    """timings=None keeps the stored timings."""
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET stage = ?, status = 'running', updated_at = ?, timings_json = COALESCE(?, timings_json) "
            "WHERE id = ?",
            (stage, _utcnow(), json.dumps(timings) if timings is not None else None, job_id),
        )


def complete_job(
    job_id: str,
    result: dict[str, Any],
    align_quality: float,
    align_ok: bool,
    align_method: str,
    images: dict[str, str],
    timings: dict[str, float],
    warnings: list[str],
) -> None:
    now = _utcnow()
    summary = result.get("summary", "")
    changes = result.get("changes", [])
    with connect() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET status = 'done',
                stage = 'done',
                updated_at = ?,
                align_quality = ?,
                align_ok = ?,
                align_method = ?,
                changes_count = ?,
                summary = ?,
                result_json = ?,
                timings_json = ?,
                warnings_json = ?,
                images_json = ?
            WHERE id = ?
            """,
            (
                now,
                align_quality,
                1 if align_ok else 0,
                align_method,
                len(changes),
                summary,
                json.dumps(result),
                json.dumps(timings),
                json.dumps(warnings),
                json.dumps(images),
                job_id,
            ),
        )


def fail_job(job_id: str, error_message: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'error', stage = 'error', updated_at = ?, error_message = ? WHERE id = ?",
            (_utcnow(), error_message, job_id),
        )


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_dict(row) for row in rows]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["job_id"] = d.pop("id")
    d["align_ok"] = bool(d.get("align_ok"))
    for key, column, empty in _JSON_FIELDS:
        d[key] = json.loads(d.get(column) or empty)
    return d


def prune_old_jobs(max_count: int = 50, max_age_hours: int = 24) -> int:
    """Removes records beyond max_count or older than max_age_hours, and deletes their output files."""
    init_db()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).replace(tzinfo=None).isoformat()
    with connect() as conn:
        expired = conn.execute("SELECT id FROM jobs WHERE created_at < ?", (cutoff_iso,)).fetchall()
        overflow = conn.execute(
            "SELECT id FROM jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?", (max_count,)
        ).fetchall()
        ids_to_remove = {r["id"] for r in expired + overflow}
        conn.executemany("DELETE FROM jobs WHERE id = ?", [(jid,) for jid in ids_to_remove])
    for jid in ids_to_remove:  # their output directories, once the rows are gone
        job_dir = DB_DIR / jid
        if job_dir.is_dir():
            shutil.rmtree(job_dir, ignore_errors=True)
    return len(ids_to_remove)
