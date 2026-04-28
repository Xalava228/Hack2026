"""Оркестратор полного пайплайна генерации презентации.

Шаги:
  1) План презентации через LLM (структура слайдов).
  2) Параллельная генерация картинок через Yandex ART.
  3) Сборка PPTX и/или PDF.
  4) Возврат путей к файлам.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from . import config
from .ai_client import AIClient, ImageBackend
from .pdf_builder import build_pdf
from .pptx_builder import build_pptx
from .slide_planner import (
    ImagesMode,
    PresentationPlan,
    TextDensity,
    plan_presentation,
)

logger = logging.getLogger(__name__)

OutputFormat = Literal["pptx", "pdf", "both"]
ProgressCallback = Callable[[str, float, str], None]


@dataclass
class JobResult:
    job_id: str
    plan: PresentationPlan
    pptx_path: Path | None = None
    pdf_path: Path | None = None
    images_used: int = 0
    elapsed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.plan.title,
            "subtitle": self.plan.subtitle,
            "slides": len(self.plan.slides),
            "images_used": self.images_used,
            "elapsed_sec": round(self.elapsed, 2),
            "pptx": self.pptx_path.name if self.pptx_path else None,
            "pdf": self.pdf_path.name if self.pdf_path else None,
            "outline": [
                {"kind": s.kind, "title": s.title, "subtitle": s.subtitle}
                for s in self.plan.slides
            ],
        }


@dataclass
class JobState:
    job_id: str
    status: str = "queued"
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None
    result: JobResult | None = None

    def update(self, stage: str, progress: float, message: str) -> None:
        self.status = "running"
        self.stage = stage
        self.progress = max(0.0, min(1.0, progress))
        self.message = message
        logger.info("[%s] %s (%.0f%%) — %s", self.job_id, stage, self.progress * 100, message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "result": self.result.to_dict() if self.result else None,
        }


JOBS: dict[str, JobState] = {}


def _safe_filename(s: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_ " else "_" for c in s).strip()
    return (out or "presentation")[:60]


async def _generate_one_image(
    client: AIClient,
    idx: int,
    prompt: str,
    backend: ImageBackend,
    aspect: str,
) -> tuple[int, bytes | None]:
    try:
        data = await client.generate_image(prompt, backend=backend, aspect=aspect)
        return idx, data
    except Exception:
        logger.exception("Не удалось сгенерировать картинку для слайда %d", idx)
        return idx, None


async def run_pipeline(
    *,
    job_id: str,
    user_prompt: str,
    n_slides: int,
    text_density: TextDensity,
    images_mode: ImagesMode,
    output_format: OutputFormat,
    image_backend: ImageBackend = "yandex-art",
) -> JobResult:
    """Полный пайплайн. Обновляет статус джобы по ходу."""
    state = JOBS[job_id]
    started = time.time()
    client = AIClient()

    state.update("planning", 0.05, "Спрашиваем у LLM структуру презентации…")
    plan = await plan_presentation(
        client,
        user_prompt=user_prompt,
        n_slides=n_slides,
        text_density=text_density,
        images_mode=images_mode,
    )
    state.update("planned", 0.25, f"Готов план «{plan.title}» на {len(plan.slides)} слайдов.")

    images: dict[int, bytes] = {}
    if images_mode == "with-images":
        prompt_targets = [
            (i, s.image_prompt)
            for i, s in enumerate(plan.slides)
            if s.image_prompt and s.kind not in ("section",)
        ]
        if prompt_targets:
            state.update(
                "images",
                0.30,
                f"Генерируем {len(prompt_targets)} изображений (Yandex ART)…",
            )
            sem = asyncio.Semaphore(3)

            async def _bound(i: int, p: str) -> tuple[int, bytes | None]:
                async with sem:
                    return await _generate_one_image(
                        client, i, p, image_backend, "16:9"
                    )

            tasks = [asyncio.create_task(_bound(i, p)) for i, p in prompt_targets]
            done = 0
            for fut in asyncio.as_completed(tasks):
                i, data = await fut
                done += 1
                if data is not None:
                    images[i] = data
                state.update(
                    "images",
                    0.30 + 0.5 * (done / max(1, len(tasks))),
                    f"Картинок готово: {done}/{len(tasks)}",
                )

    state.update("rendering", 0.85, "Собираем файлы презентации…")
    base_name = _safe_filename(plan.title)
    out_pptx: Path | None = None
    out_pdf: Path | None = None
    if output_format in ("pptx", "both"):
        out_pptx = config.OUTPUT_DIR / f"{job_id}__{base_name}.pptx"
        build_pptx(plan, images, out_pptx)
    if output_format in ("pdf", "both"):
        out_pdf = config.OUTPUT_DIR / f"{job_id}__{base_name}.pdf"
        build_pdf(plan, images, out_pdf)

    elapsed = time.time() - started
    result = JobResult(
        job_id=job_id,
        plan=plan,
        pptx_path=out_pptx,
        pdf_path=out_pdf,
        images_used=len(images),
        elapsed=elapsed,
    )
    state.status = "done"
    state.stage = "done"
    state.progress = 1.0
    state.message = "Готово!"
    state.finished_at = time.time()
    state.result = result
    return result


def create_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = JobState(job_id=job_id)
    return job_id


async def run_job_async(job_id: str, **kwargs) -> None:
    try:
        await run_pipeline(job_id=job_id, **kwargs)
    except Exception as e:
        logger.exception("Job %s упал", job_id)
        st = JOBS.get(job_id)
        if st is not None:
            st.status = "error"
            st.error = str(e)
            st.finished_at = time.time()
