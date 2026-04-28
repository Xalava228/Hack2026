"""FastAPI-бэкенд: HTTP API + раздача статики (frontend)."""
from __future__ import annotations

import asyncio
import base64
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
from .engagement import analyze_plan_engagement
from .ai_client import AIClient, AIClientError
from .orchestrator import JOBS, create_job, run_job_async, run_render_job_async
from .sample_analyzer import SampleAnalysis, analyze_file
from .slide_planner import (
    plan_from_dict,
    plan_presentation,
    plan_presentation_from_sample,
    regenerate_slide,
)
from .web_research import collect_web_context

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
    images_mode: str = Field("with-images", pattern="^(with-images|no-images|internet-images)$")
    output_format: str = Field("both", pattern="^(pptx|pdf|both)$")
    image_backend: str = Field("yandex-art", pattern="^(yandex-art|sd|internet)$")
    research_mode: str = Field("off", pattern="^(off|web)$")
    sample_id: str | None = None
    design_preset: str = Field(
        "fresh",
        pattern="^(fresh|ocean|sunrise|midnight|pastel|forest)$",
    )


class PlanRequest(GenerateRequest):
    pass


class RenderRequest(BaseModel):
    plan: dict
    images_mode: str = Field("with-images", pattern="^(with-images|no-images|internet-images)$")
    output_format: str = Field("both", pattern="^(pptx|pdf|both)$")
    image_backend: str = Field("yandex-art", pattern="^(yandex-art|sd|internet)$")


class RegenerateSlideRequest(BaseModel):
    plan: dict
    slide_index: int = Field(..., ge=0, le=100)
    instruction: str = Field(..., min_length=3, max_length=1200)
    images_mode: str = Field("with-images", pattern="^(with-images|no-images|internet-images)$")


class EngagementRequest(BaseModel):
    plan: dict


class WebImagesRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=300)
    count: int = Field(6, ge=1, le=12)
    aspect: str = Field("16:9", pattern="^(16:9|1:1)$")


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
            design_preset=req.design_preset,
            research_mode=req.research_mode,  # type: ignore[arg-type]
        )
    )
    return {"job_id": job_id}


@app.post("/api/plan")
async def api_plan(req: PlanRequest):
    sample = None
    if req.sample_id:
        sample = SAMPLES.get(req.sample_id)
        if sample is None:
            raise HTTPException(status_code=404, detail="sample_id не найден")
    try:
        client = AIClient()
        web_context = ""
        if req.research_mode == "web":
            try:
                web_context = await collect_web_context(req.prompt)
            except Exception:
                logger.exception("collect_web_context failed, continue without web context")
                web_context = ""
        if sample is None:
            plan = await plan_presentation(
                client,
                user_prompt=req.prompt,
                n_slides=req.n_slides,
                text_density=req.text_density,  # type: ignore[arg-type]
                images_mode=req.images_mode,  # type: ignore[arg-type]
                design_preset=req.design_preset,
                web_context=web_context,
            )
        else:
            plan = await plan_presentation_from_sample(
                client,
                user_prompt=req.prompt,
                sample=sample,
                n_slides=req.n_slides,
                images_mode=req.images_mode,  # type: ignore[arg-type]
                text_density=req.text_density,  # type: ignore[arg-type]
                design_preset=req.design_preset,
                web_context=web_context,
            )
    except AIClientError as e:
        logger.warning("api_plan: AI unavailable: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Сервис ИИ временно недоступен (проблема сети/доступа к AI API). Проверьте VPN/прокси/интернет и повторите.",
        )
    except Exception:
        logger.exception("api_plan failed unexpectedly")
        raise HTTPException(status_code=500, detail="Не удалось собрать план презентации.")
    return {"plan": plan.to_dict()}


@app.post("/api/render")
async def api_render(req: RenderRequest):
    try:
        _ = plan_from_dict(req.plan)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid plan: {e}")
    job_id = create_job()
    asyncio.create_task(
        run_render_job_async(
            job_id,
            plan_data=req.plan,
            images_mode=req.images_mode,  # type: ignore[arg-type]
            output_format=req.output_format,  # type: ignore[arg-type]
            image_backend=req.image_backend,  # type: ignore[arg-type]
        )
    )
    return {"job_id": job_id}


@app.post("/api/regenerate-slide")
async def api_regenerate_slide(req: RegenerateSlideRequest):
    try:
        plan = plan_from_dict(req.plan)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid plan: {e}")
    if req.slide_index >= len(plan.slides):
        raise HTTPException(status_code=400, detail="slide_index out of range")
    try:
        client = AIClient()
        slide = await regenerate_slide(
            client,
            plan=plan,
            slide_index=req.slide_index,
            instruction=req.instruction,
            images_mode=req.images_mode,  # type: ignore[arg-type]
        )
    except AIClientError:
        raise HTTPException(
            status_code=503,
            detail="Сервис ИИ временно недоступен для перегенерации слайда.",
        )
    old = req.plan.get("slides", [])
    if isinstance(old, list) and req.slide_index < len(old) and isinstance(old[req.slide_index], dict):
        old_data_url = str(old[req.slide_index].get("image_data_url", "")).strip()
        if old_data_url:
            slide.image_data_url = old_data_url
    return {"slide": slide.to_dict()}


@app.post("/api/engagement-heatmap")
async def api_engagement_heatmap(req: EngagementRequest):
    try:
        plan = plan_from_dict(req.plan)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid plan: {e}")
    return analyze_plan_engagement(plan)


@app.post("/api/web-images")
async def api_web_images(req: WebImagesRequest):
    client = AIClient()
    images = await client.internet_image_candidates(req.query, count=req.count, aspect=req.aspect)
    encoded = [
        f"data:image/jpeg;base64,{base64.b64encode(img).decode('ascii')}"
        for img in images
    ]
    return {"query": req.query, "items": encoded}


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
