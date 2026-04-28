"""Проверка валидности сгенерированных файлов."""
from __future__ import annotations

import os
import sys

from pptx import Presentation


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    folder = "generated"
    if not os.path.isdir(folder):
        print("Папка generated/ пуста")
        return 1
    for f in sorted(os.listdir(folder)):
        full = os.path.join(folder, f)
        size = os.path.getsize(full)
        if f.lower().endswith(".pptx"):
            try:
                p = Presentation(full)
                print(f"PPTX OK: {f} | {len(p.slides)} slides | {size} bytes")
            except Exception as e:
                print(f"PPTX FAIL: {f} | {e}")
        elif f.lower().endswith(".pdf"):
            with open(full, "rb") as fh:
                head = fh.read(4)
            status = "OK" if head == b"%PDF" else "FAIL"
            print(f"PDF {status}: {f} | {size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
