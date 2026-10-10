"""PERSON 3: FastAPI app. Run: uvicorn app.main:app --reload (from backend/)."""
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from . import pipeline  # noqa: E402
from .contracts import AnalyzeResponse  # noqa: E402

pipeline.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Zvalgas AI")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/api/files", StaticFiles(directory=pipeline.OUTPUT_DIR), name="files")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_endpoint(
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    criteria: str = Form(...),
    lang: str = Form("en"),
):
    try:
        return pipeline.run(await image_a.read(), await image_b.read(), criteria, lang)
    except ValueError as e:
        raise HTTPException(400, str(e))
