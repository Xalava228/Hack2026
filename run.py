"""Локальный запуск БПК-IT_ver.3.0.

    python run.py            # http://127.0.0.1:8000
"""
from __future__ import annotations

import os

import uvicorn


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "backend.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
