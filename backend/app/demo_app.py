"""Demo prep server: the production API, unchanged, plus the demo cache endpoints (/api/demo, see docs/demo.md).

    cd backend && uvicorn app.demo_app:app --port 8010      (demo.ps1 prep starts it with live-AI settings)

app.main:app is mounted as it is, so prep runs the exact production analysis, and the operator terminal on :8000
never sees the demo routes. A mounted app gets no lifespan: this process starts neither the watch folder nor the
batch worker, and never re-queues batches, so it can run next to the operator terminal on the same database."""
from fastapi import FastAPI

from .demo.routes import router
from .main import app as production_app

app = FastAPI(title="Zvalgas AI - Demo Prep")
app.include_router(router)
app.mount("/", production_app)
