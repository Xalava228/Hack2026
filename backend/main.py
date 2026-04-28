"""FastAPI-бэкенд: HTTP API + раздача статики (frontend)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import shutil
import uuid

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .orchestrator import JOBS, create_job, run_job_async
from .sample_analyzer import SampleAnalysis, analyze_file

SAMPLES: dict[str, SampleAnalysis] = {}

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
    sample_id: str | None = None


_ALLOWED_SUFFIX = {".pptx", ".pdf"}
_MAX_UPLOAD_BYTES = 30 * 1024 * 1024  # 30 MB


@app.post("/api/analyze")
async def api_analyze(file: UploadFile = File(...)):
    """Принять PPTX/PDF, проанализировать структуру и палитру, вернуть summary."""
    name = file.filename or "sample"
    suffix = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if suffix not in _ALLOWED_SUFFIX:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только файлы .pptx и .pdf",
        )

    sample_id = uuid.uuid4().hex[:12]
    safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:120]
    dest = config.UPLOADS_DIR / f"{sample_id}__{safe_name}"
    size = 0
    with dest.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_UPLOAD_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Файл слишком большой (>30 МБ)")
            f.write(chunk)

    try:
        analysis = analyze_file(dest, sample_id=sample_id)
    except Exception as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Не удалось разобрать файл: {e}")

    SAMPLES[sample_id] = analysis
    return JSONResponse(analysis.short_summary())


@app.delete("/api/samples/{sample_id}")
async def api_delete_sample(sample_id: str):
    sample = SAMPLES.pop(sample_id, None)
    if sample is None:
        raise HTTPException(status_code=404, detail="sample not found")
    for f in config.UPLOADS_DIR.glob(f"{sample_id}__*"):
        try:
            f.unlink()
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/generate")
async def api_generate(req: GenerateRequest):
    sample = None
    if req.sample_id:
        sample = SAMPLES.get(req.sample_id)
        if sample is None:
            raise HTTPException(status_code=404, detail="sample_id не найден")

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
            sample=sample,
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
        "samples": len(SAMPLES),
    }


_ = shutil  # noqa: F401  (импорт оставлен для будущей чистки uploads)


_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="static")
