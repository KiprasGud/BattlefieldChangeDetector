"""PERSON 3: SQLite database for mission history, stage updates, and disk pruning."""
import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

DB_DIR = Path(__file__).resolve().parents[2] / "output"
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DB_DIR / "zvalgas.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
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
        conn.commit()


def create_job(job_id: str, criteria: str, lang: str = "en") -> dict[str, Any]:
    init_db()
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, created_at, updated_at, status, stage, criteria, lang, timings_json, warnings_json)
            VALUES (?, ?, ?, 'queued', 'queued', ?, ?, '{}', '[]')
            """,
            (job_id, now, now, criteria, lang),
        )
        conn.commit()
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
    now = datetime.utcnow().isoformat()
    timings_str = json.dumps(timings) if timings is not None else None
    with get_connection() as conn:
        if timings_str:
            conn.execute(
                "UPDATE jobs SET stage = ?, status = 'running', updated_at = ?, timings_json = ? WHERE id = ?",
                (stage, now, timings_str, job_id),
            )
        else:
            conn.execute(
                "UPDATE jobs SET stage = ?, status = 'running', updated_at = ? WHERE id = ?",
                (stage, now, job_id),
            )
        conn.commit()


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
    now = datetime.utcnow().isoformat()
    summary = result.get("summary", "")
    changes = result.get("changes", [])
    with get_connection() as conn:
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
        conn.commit()


def fail_job(job_id: str, error_message: str) -> None:
    now = datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = 'error', stage = 'error', updated_at = ?, error_message = ? WHERE id = ?",
            (now, error_message, job_id),
        )
        conn.commit()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        return _row_to_dict(row)


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))
        return [_row_to_dict(row) for row in cur.fetchall()]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["job_id"] = d.pop("id")
    d["align_ok"] = bool(d.get("align_ok"))
    if d.get("result_json"):
        d["result"] = json.loads(d["result_json"])
    else:
        d["result"] = None

    if d.get("timings_json"):
        d["timings"] = json.loads(d["timings_json"])
    else:
        d["timings"] = {}

    if d.get("warnings_json"):
        d["warnings"] = json.loads(d["warnings_json"])
    else:
        d["warnings"] = []

    if d.get("images_json"):
        d["images"] = json.loads(d["images_json"])
    else:
        d["images"] = {}
    return d


def prune_old_jobs(max_count: int = 50, max_age_hours: int = 24) -> int:
    """Removes records beyond max_count or older than max_age_hours, and deletes their output files."""
    init_db()
    now_ts = time.time()
    cutoff_ts = now_ts - (max_age_hours * 3600)
    cutoff_iso = datetime.utcfromtimestamp(cutoff_ts).isoformat()

    deleted_count = 0
    with get_connection() as conn:
        # 1. Prune by age
        cur = conn.execute("SELECT id FROM jobs WHERE created_at < ?", (cutoff_iso,))
        expired_ids = [r["id"] for r in cur.fetchall()]

        # 2. Prune by max_count
        cur = conn.execute("SELECT id FROM jobs ORDER BY created_at DESC LIMIT -1 OFFSET ?", (max_count,))
        overflow_ids = [r["id"] for r in cur.fetchall()]

        ids_to_remove = set(expired_ids + overflow_ids)
        for jid in ids_to_remove:
            conn.execute("DELETE FROM jobs WHERE id = ?", (jid,))
            # Delete output directory for job
            job_dir = DB_DIR / jid
            if job_dir.exists() and job_dir.is_dir():
                shutil.rmtree(job_dir, ignore_errors=True)
            deleted_count += 1
        conn.commit()

    return deleted_count
