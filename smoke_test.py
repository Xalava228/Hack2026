"""Быстрая проверка живости API: LLM + генерация одной картинки.

    python smoke_test.py
"""
from __future__ import annotations

import asyncio
import sys
import traceback

from backend.ai_client import AIClient


async def main() -> int:
    client = AIClient()
    print(f"Base URL: {client.base_url}")
    print(f"Token: {client.token[:20]}…{client.token[-10:]}")

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

    print("\n[1/2] LLM ping...")
    try:
        text = await client.chat(
            "Ответь одним коротким предложением: что такое презентация?",
            max_new_tokens=80,
            temperature=0.2,
        )
        print(f"  OK -> {text[:200]}")
    except Exception:
        print("  FAIL:")
        traceback.print_exc()
        return 1

    print("\n[2/2] Yandex ART -> 1 картинка...")
    try:
        data = await client.generate_image(
            "minimalist illustration of a cat reading a book", aspect="16:9"
        )
        print(f"  OK -> получено {len(data)} байт")
        out = "smoke_image.png"
        with open(out, "wb") as f:
            f.write(data)
        print(f"  Сохранено: {out}")
    except Exception:
        print("  FAIL:")
        traceback.print_exc()
        return 2

    print("\nВсё ок -- API живой.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
