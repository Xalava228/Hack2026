"""Конфигурация приложения. Читает токен и URL из переменных окружения."""
from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_ROOT = Path(__file__).resolve().parent.parent
_load_dotenv(_ROOT / ".env")
_load_dotenv(_ROOT / ".env.example")


AI_TOKEN: str = os.environ.get("AI_TOKEN", "").strip()
AI_BASE_URL: str = os.environ.get("AI_BASE_URL", "https://ai.rt.ru/api/1.0").rstrip("/")

OUTPUT_DIR: Path = _ROOT / "generated"
OUTPUT_DIR.mkdir(exist_ok=True)

ASSETS_DIR: Path = _ROOT / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

UPLOADS_DIR: Path = _ROOT / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

LLM_MODEL: str = os.environ.get("LLM_MODEL", "Qwen/Qwen2.5-72B-Instruct")
