"""Планирование структуры презентации через LLM.

LLM получает промпт пользователя + параметры (кол-во слайдов, тип контента,
нужны ли картинки) и возвращает JSON со структурой презентации.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .ai_client import AIClient

logger = logging.getLogger(__name__)


TextDensity = Literal["minimal", "balanced", "detailed"]
ImagesMode = Literal["with-images", "no-images"]
SlideKind = Literal["title", "content", "two_column", "section", "conclusion"]


@dataclass
class SlideSpec:
    kind: SlideKind
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    body: str = ""
    image_prompt: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "bullets": list(self.bullets),
            "body": self.body,
            "image_prompt": self.image_prompt,
            "notes": self.notes,
        }


@dataclass
class PresentationPlan:
    title: str
    subtitle: str
    theme: str
    palette: dict[str, str]
    slides: list[SlideSpec]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "theme": self.theme,
            "palette": self.palette,
            "slides": [s.to_dict() for s in self.slides],
        }


_DEFAULT_PALETTE = {
    "primary": "#1F2937",
    "accent": "#6366F1",
    "background": "#FFFFFF",
    "text": "#111827",
    "muted": "#6B7280",
}


def _build_prompt(
    user_prompt: str,
    n_slides: int,
    text_density: TextDensity,
    images_mode: ImagesMode,
    language: str,
) -> str:
    density_hint = {
        "minimal": "минимум текста: 2–3 коротких буллета на слайде, по 4–8 слов",
        "balanced": "сбалансированный текст: 3–5 буллетов на слайде, по 6–14 слов",
        "detailed": "развёрнутый текст: 4–6 буллетов или абзац на 2–4 предложения",
    }[text_density]
    images_hint = (
        "Для каждого контентного слайда придумай поле image_prompt — короткое описание "
        "иллюстрации на английском языке (без текста на изображении), подходящей по смыслу."
        if images_mode == "with-images"
        else "Поле image_prompt оставляй пустой строкой — изображения не нужны."
    )

    schema = {
        "title": "string — заголовок презентации",
        "subtitle": "string — подзаголовок/слоган",
        "theme": "string — название темы (одно-два слова)",
        "palette": {
            "primary": "#RRGGBB — основной цвет",
            "accent": "#RRGGBB — акцент",
            "background": "#RRGGBB — фон",
            "text": "#RRGGBB — текст",
            "muted": "#RRGGBB — приглушённый",
        },
        "slides": [
            {
                "kind": "title|content|two_column|section|conclusion",
                "title": "string",
                "subtitle": "string (опционально)",
                "bullets": ["string", "..."],
                "body": "string — связный текст (опционально, вместо/в дополнение к bullets)",
                "image_prompt": "string — промпт для генерации картинки на английском",
                "notes": "string — заметки докладчика (опционально)",
            }
        ],
    }

    return f"""Ты — опытный designer-консультант по презентациям.
Создай структуру презентации СТРОГО в формате JSON, без обрамляющего текста и без ```json.

Параметры:
- Запрос пользователя: «{user_prompt}»
- Количество слайдов: ровно {n_slides}
- Плотность текста: {density_hint}
- Изображения: {images_hint}
- Язык контента: {language}

Требования:
1. Первый слайд — kind="title" (заголовок + подзаголовок).
2. Последний слайд — kind="conclusion" (выводы / call-to-action).
3. Внутренние слайды — преимущественно kind="content"; можешь добавить 1 "section" (раздел-разделитель)
   и 1 "two_column" (двухколоночный) для разнообразия, если уместно.
4. Палитра — гармоничная, стильная, читаемая (тёмный текст на светлом фоне или наоборот).
5. Заголовки слайдов — короткие (до 60 символов), без точек в конце.
6. Не повторяйся, не выдумывай факты — давай обобщения и структуру.
7. Верни ТОЛЬКО валидный JSON следующей формы:

{json.dumps(schema, ensure_ascii=False, indent=2)}

Сейчас сгенерируй JSON для запроса «{user_prompt}» на {n_slides} слайдов.
"""


def _detect_language(text: str) -> str:
    cyrillic = sum(1 for ch in text if "А" <= ch <= "я" or ch in "ёЁ")
    return "русский" if cyrillic >= 3 else "английский"


def _extract_json(raw: str) -> dict[str, Any]:
    """Достаём JSON из ответа LLM (часто оборачивается в ```json ... ```)."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL | re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON не найден в ответе LLM:\n{raw[:500]}")
    candidate = raw[start : end + 1]
    return json.loads(candidate)


def _coerce_slide(d: dict[str, Any], idx: int, total: int) -> SlideSpec:
    raw_kind = str(d.get("kind") or d.get("type") or "").strip().lower()
    kind: SlideKind
    if raw_kind in ("title", "cover"):
        kind = "title"
    elif raw_kind in ("conclusion", "outro", "summary", "end"):
        kind = "conclusion"
    elif raw_kind in ("section", "divider"):
        kind = "section"
    elif raw_kind in ("two_column", "two-column", "twocolumn", "split"):
        kind = "two_column"
    else:
        if idx == 0:
            kind = "title"
        elif idx == total - 1:
            kind = "conclusion"
        else:
            kind = "content"

    bullets_raw = d.get("bullets") or d.get("points") or []
    if isinstance(bullets_raw, str):
        bullets = [b.strip(" -•\t") for b in bullets_raw.splitlines() if b.strip()]
    else:
        bullets = [str(b).strip(" -•\t") for b in bullets_raw if str(b).strip()]

    return SlideSpec(
        kind=kind,
        title=str(d.get("title", "")).strip() or f"Слайд {idx + 1}",
        subtitle=str(d.get("subtitle", "")).strip(),
        bullets=bullets,
        body=str(d.get("body", "")).strip(),
        image_prompt=str(d.get("image_prompt", "")).strip(),
        notes=str(d.get("notes", "")).strip(),
    )


def _coerce_palette(p: Any) -> dict[str, str]:
    out = dict(_DEFAULT_PALETTE)
    if isinstance(p, dict):
        for k, v in p.items():
            if isinstance(v, str) and re.fullmatch(r"#?[0-9A-Fa-f]{6}", v.strip()):
                value = v.strip()
                if not value.startswith("#"):
                    value = "#" + value
                out[str(k)] = value
    return out


async def plan_presentation(
    client: AIClient,
    user_prompt: str,
    n_slides: int,
    text_density: TextDensity = "balanced",
    images_mode: ImagesMode = "with-images",
) -> PresentationPlan:
    """Сгенерировать план презентации через LLM."""
    n_slides = max(3, min(int(n_slides), 25))
    language = _detect_language(user_prompt)
    prompt = _build_prompt(user_prompt, n_slides, text_density, images_mode, language)

    raw = await client.chat(
        prompt,
        system_prompt=(
            "Ты возвращаешь СТРОГО валидный JSON без пояснений и без markdown-обёртки. "
            "Никакого текста до или после JSON."
        ),
        max_new_tokens=4096,
        temperature=0.5,
    )
    logger.debug("LLM raw plan: %s", raw[:500])

    try:
        data = _extract_json(raw)
    except Exception as e:
        logger.exception("Не удалось распарсить JSON от LLM, делаю ретрай")
        raw = await client.chat(
            prompt
            + "\n\nВНИМАНИЕ: предыдущий ответ не был валидным JSON. Верни только JSON.",
            system_prompt="Возвращай только валидный JSON.",
            max_new_tokens=4096,
            temperature=0.2,
        )
        data = _extract_json(raw)

    slides_raw = data.get("slides") or []
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ValueError("LLM вернула пустой массив slides")

    if len(slides_raw) > n_slides:
        slides_raw = slides_raw[:n_slides]
    slides = [_coerce_slide(s, i, len(slides_raw)) for i, s in enumerate(slides_raw)]

    if images_mode == "no-images":
        for s in slides:
            s.image_prompt = ""

    return PresentationPlan(
        title=str(data.get("title", "")).strip() or "Без названия",
        subtitle=str(data.get("subtitle", "")).strip(),
        theme=str(data.get("theme", "")).strip() or "general",
        palette=_coerce_palette(data.get("palette")),
        slides=slides,
    )
