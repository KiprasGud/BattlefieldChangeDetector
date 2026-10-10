"""PERSON 3: Storage package for job history and database management.

Batch review records (watch-folder pipeline) live in .batches, imported as a module: from .storage import batches."""
from .db import (
    complete_job,
    create_job,
    fail_job,
    get_job,
    init_db,
    list_jobs,
    prune_old_jobs,
    update_job_stage,
)

__all__ = [
    "init_db",
    "create_job",
    "update_job_stage",
    "complete_job",
    "fail_job",
    "get_job",
    "list_jobs",
    "prune_old_jobs",
]
