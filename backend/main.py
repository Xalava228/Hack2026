"""FastAPI-бэкенд: HTTP API + раздача статики (frontend)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .orchestrator import JOBS, create_job, run_job_async

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="AI Presentation Generator", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=2000)
    n_slides: int = Field(8, ge=3, le=25)
    text_density: str = Field("balanced", pattern="^(minimal|balanced|detailed)$")
    images_mode: str = Field("with-images", pattern="^(with-images|no-images)$")
    output_format: str = Field("both", pattern="^(pptx|pdf|both)$")
    image_backend: str = Field("yandex-art", pattern="^(yandex-art|sd)$")


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    job_id = create_job()
    asyncio.create_task(
        run_job_async(
            job_id,
            user_prompt=req.prompt,
            n_slides=req.n_slides,
            text_density=req.text_density,  # type: ignore[arg-type]
            images_mode=req.images_mode,  # type: ignore[arg-type]
            output_format=req.output_format,  # type: ignore[arg-type]
            image_backend=req.image_backend,  # type: ignore[arg-type]
        )
    )
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
async def api_job_status(job_id: str):
    st = JOBS.get(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JSONResponse(st.to_dict())


@app.get("/api/jobs/{job_id}/file/{kind}")
async def api_job_file(job_id: str, kind: str):
    st = JOBS.get(job_id)
    if st is None or st.result is None:
        raise HTTPException(status_code=404, detail="result not ready")
    res = st.result
    if kind == "pptx" and res.pptx_path and res.pptx_path.exists():
        return FileResponse(
            res.pptx_path,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=res.pptx_path.name,
        )
    if kind == "pdf" and res.pdf_path and res.pdf_path.exists():
        return FileResponse(
            res.pdf_path, media_type="application/pdf", filename=res.pdf_path.name
        )
    raise HTTPException(status_code=404, detail="file not found")


@app.get("/api/health")
async def api_health():
    return {
        "ok": True,
        "ai_token_set": bool(config.AI_TOKEN),
        "ai_base_url": config.AI_BASE_URL,
        "active_jobs": sum(1 for j in JOBS.values() if j.status == "running"),
    }


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="static")
