"""End-to-end проверка пайплайна без поднятия HTTP-сервера."""
from __future__ import annotations

import asyncio
import sys
import time

from backend.orchestrator import JOBS, JobState, run_pipeline


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    job_id = "itest1"
    JOBS[job_id] = JobState(job_id=job_id)

    t0 = time.time()
    result = await run_pipeline(
        job_id=job_id,
        user_prompt="Влияние искусственного интеллекта на современное образование",
        n_slides=5,
        text_density="balanced",
        images_mode="with-images",
        output_format="both",
        image_backend="yandex-art",
    )
    print(f"\nDONE за {time.time() - t0:.1f} сек")
    print(f"  Title:  {result.plan.title}")
    print(f"  Slides: {len(result.plan.slides)}")
    print(f"  Images: {result.images_used}")
    print(f"  PPTX:   {result.pptx_path}")
    print(f"  PDF:    {result.pdf_path}")
    for i, s in enumerate(result.plan.slides):
        print(f"   {i+1}. [{s.kind}] {s.title}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
