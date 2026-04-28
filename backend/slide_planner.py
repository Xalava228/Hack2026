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
from .design_presets import (
    DEFAULT_PRESET,
    PRESET_LABELS_RU,
    canonical_preset_id,
    normalize_plan_palette,
)
from .sample_analyzer import SampleAnalysis, sample_outline_for_llm

logger = logging.getLogger(__name__)


TextDensity = Literal["minimal", "balanced", "detailed"]
ImagesMode = Literal["with-images", "no-images"]
SlideKind = Literal["title", "content", "two_column", "section", "conclusion", "table"]


@dataclass
class SlideSpec:
    kind: SlideKind
    title: str
    subtitle: str = ""
    bullets: list[str] = field(default_factory=list)
    body: str = ""
    image_prompt: str = ""
    image_data_url: str = ""
    notes: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    style: dict[str, str] = field(default_factory=dict)
    image_placement: str = "right"

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "bullets": list(self.bullets),
            "body": self.body,
            "image_prompt": self.image_prompt,
            "image_data_url": self.image_data_url,
            "notes": self.notes,
            "headers": list(self.headers),
            "rows": [list(r) for r in self.rows],
            "style": dict(self.style),
            "image_placement": self.image_placement,
        }


@dataclass
class PresentationPlan:
    title: str
    subtitle: str
    theme: str
    palette: dict[str, str]
    slides: list[SlideSpec]
    design_preset: str = "fresh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "subtitle": self.subtitle,
            "theme": self.theme,
            "palette": self.palette,
            "design_preset": self.design_preset,
            "slides": [s.to_dict() for s in self.slides],
        }


def _normalize_kind(raw_kind: str, idx: int, total: int) -> SlideKind:
    rk = raw_kind.strip().lower()
    if rk in ("title", "cover"):
        return "title"
    if rk in ("conclusion", "outro", "summary", "end"):
        return "conclusion"
    if rk in ("section", "divider"):
        return "section"
    if rk in ("two_column", "two-column", "twocolumn", "split"):
        return "two_column"
    if rk in ("table", "comparison", "compare", "matrix", "spec", "specs", "specifications"):
        return "table"
    if idx == 0:
        return "title"
    if idx == total - 1:
        return "conclusion"
    return "content"


def _coerce_table(d: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    """Привести таблицу LLM-а к виду headers + прямоугольный rows."""
    headers_raw = d.get("headers") or d.get("columns") or []
    if isinstance(headers_raw, str):
        headers_raw = [h.strip() for h in headers_raw.split("|") if h.strip()]
    headers = [str(h).strip() for h in headers_raw if str(h).strip()]
    headers = headers[:6]  # держим разумный максимум

    rows_raw = d.get("rows") or d.get("data") or []
    rows: list[list[str]] = []
    if isinstance(rows_raw, list):
        for r in rows_raw:
            if isinstance(r, list):
                cells = [str(c).strip() for c in r]
            elif isinstance(r, dict):
                cells = [str(r.get(h, "")).strip() for h in headers] if headers else [str(v).strip() for v in r.values()]
            elif isinstance(r, str):
                cells = [c.strip() for c in r.split("|")]
            else:
                cells = [str(r).strip()]
            if any(c for c in cells):
                rows.append(cells)
    rows = rows[:8]

    if headers:
        # выравниваем длины строк под количество колонок
        n = len(headers)
        rows = [(r + [""] * n)[:n] for r in rows]
    elif rows:
        # колонок не было — берём максимум по строкам
        n = max(len(r) for r in rows)
        headers = [f"Колонка {i + 1}" for i in range(n)]
        rows = [(r + [""] * n)[:n] for r in rows]

    return headers, rows


_DEFAULT_PALETTE = {
    "primary": "#1F2937",
    "accent": "#6366F1",
    "background": "#FFFFFF",
    "text": "#111827",
    "muted": "#6B7280",
}


_DENSITY_RULES: dict[str, dict[str, Any]] = {
    "minimal": {
        "label": "минимальный",
        "rule": (
            "максимум 3 буллета на слайде, каждый по 3–7 слов; "
            "поле body оставляй пустым; subtitle — не длиннее 8 слов; "
            "никаких длинных предложений и пояснений"
        ),
        "max_bullets": 3,
        "max_bullet_words": 7,
        "allow_body": False,
    },
    "balanced": {
        "label": "краткий",
        "rule": (
            "от 3 до 5 буллетов на слайде, каждый по 6–14 слов; "
            "body допустим только короткий (до 1 предложения) и только если буллетов меньше 4"
        ),
        "max_bullets": 5,
        "max_bullet_words": 14,
        "allow_body": True,
    },
    "detailed": {
        "label": "подробный",
        "rule": (
            "4–6 буллетов на слайде ИЛИ связный body из 2–4 предложений; "
            "буллеты до 16 слов; раскрывай суть конкретными формулировками, без воды"
        ),
        "max_bullets": 6,
        "max_bullet_words": 16,
        "allow_body": True,
    },
}


def _density_block(text_density: TextDensity) -> str:
    spec = _DENSITY_RULES.get(text_density, _DENSITY_RULES["balanced"])
    return (
        f"ПЛОТНОСТЬ ТЕКСТА: «{spec['label']}». "
        f"СТРОГО: {spec['rule']}. "
        "Эти ограничения ВАЖНЕЕ красоты — не нарушай их даже если хочется добавить деталей."
    )


def _build_prompt(
    user_prompt: str,
    n_slides: int,
    text_density: TextDensity,
    images_mode: ImagesMode,
    language: str,
    *,
    preset_label: str = "",
) -> str:
    density_block = _density_block(text_density)
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
            "primary": "#RRGGBB — заголовки",
            "accent": "#RRGGBB — акцент",
            "accent2": "#RRGGBB — вторичный акцент",
            "background": "#RRGGBB — фон",
            "surface": "#RRGGBB — карточки",
            "text": "#RRGGBB — основной текст",
            "muted": "#RRGGBB — приглушённый",
        },
        "slides": [
            {
                "kind": "title|content|two_column|section|conclusion|table",
                "title": "string",
                "subtitle": "string (опционально)",
                "bullets": ["string", "..."],
                "body": "string — связный текст (опционально, вместо/в дополнение к bullets)",
                "image_prompt": "string — промпт для генерации картинки на английском",
                "notes": "string — заметки докладчика (опционально)",
                "headers": [
                    "string — заголовки колонок (только для kind=table)"
                ],
                "rows": [
                    ["string", "..."]
                ],
            }
        ],
    }

    return f"""Ты — опытный designer-консультант по презентациям и аккуратный редактор.
Создай структуру презентации СТРОГО в формате JSON, без обрамляющего текста и без ```json.

Параметры:
- Запрос пользователя: «{user_prompt}»
- Количество слайдов: ровно {n_slides}
- {density_block}
- Изображения: {images_hint}
- Язык контента: {language}
- Визуальный пресет дизайна (выбран пользователем, цвета в экспорте применятся к пресету): {preset_label or "по умолчанию"}

Требования:
1. Первый слайд — kind="title" (заголовок + подзаголовок).
2. Последний слайд — kind="conclusion" (выводы / call-to-action).
3. Внутренние слайды — преимущественно kind="content"; можешь добавить 1 "section" (раздел-разделитель)
   и 1 "two_column" (двухколоночный) для разнообразия, если уместно.
4. ТАБЛИЦА. Если тема явно требует структурированного сравнения, спецификации, тарифа, расписания,
   статистики или матрицы критериев — добавь 1–2 слайда kind="table" с полями:
     - headers: 2–5 коротких заголовков колонок (по 1–3 слова),
     - rows: 2–7 строк, по столько же ячеек, сколько колонок; ячейка короткая (до 6 слов).
   Не используй table «для красоты» — только когда табличная форма реально полезнее буллетов.
   На table-слайде поля bullets/body оставляй пустыми. image_prompt оставляй пустым (картинки нет).
5. Поле palette можно заполнить примерными hex — точные цвета потом задаёт системный пресет «{preset_label or "пресет"}»; придерживайся тона этого стиля в формулировках.
6. Заголовки слайдов — короткие (до 60 символов), без точек в конце.
7. ФАКТЫ. Если ты не уверен в конкретной цифре, дате, имени или названии — НЕ пиши его.
   Лучше дать обобщённую формулировку, чем выдумать факт. Никаких «галлюцинаций».
   Особенно в таблицах: пустая ячейка лучше выдуманного числа.
8. Не повторяйся между слайдами и не противоречь сам себе (одни и те же утверждения с разными цифрами — недопустимо).
9. Соблюдай ограничение по плотности из пункта выше — это жёсткое правило (на table-слайды плотность не влияет).
10. Верни ТОЛЬКО валидный JSON следующей формы:

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
    raw_kind = str(d.get("kind") or d.get("type") or "")
    kind = _normalize_kind(raw_kind, idx, total)

    bullets_raw = d.get("bullets") or d.get("points") or []
    if isinstance(bullets_raw, str):
        bullets = [b.strip(" -•\t") for b in bullets_raw.splitlines() if b.strip()]
    else:
        bullets = [str(b).strip(" -•\t") for b in bullets_raw if str(b).strip()]

    headers, rows = _coerce_table(d)

    if kind == "table" and not (headers and rows):
        # LLM пометила слайд как table, но данных не дала -> деградируем в content
        kind = "content"

    style_raw = d.get("style") or {}
    style: dict[str, str] = {}
    if isinstance(style_raw, dict):
        for kk, vv in style_raw.items():
            if vv is None:
                continue
            s = str(vv).strip()
            if s:
                style[str(kk)] = s
    placing = str(d.get("image_placement") or d.get("image_side") or "right").strip().lower()
    if placing not in ("left", "right"):
        placing = "right"

    return SlideSpec(
        kind=kind,
        title=str(d.get("title", "")).strip() or f"Слайд {idx + 1}",
        subtitle=str(d.get("subtitle", "")).strip(),
        bullets=bullets,
        body=str(d.get("body", "")).strip(),
        image_prompt=str(d.get("image_prompt", "")).strip(),
        image_data_url=str(d.get("image_data_url", "")).strip(),
        notes=str(d.get("notes", "")).strip(),
        headers=headers,
        rows=rows,
        style=style,
        image_placement=placing,
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


def plan_from_dict(data: dict[str, Any]) -> PresentationPlan:
    slides_raw = data.get("slides") or []
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ValueError("slides must be a non-empty list")
    if len(slides_raw) > 25:
        slides_raw = slides_raw[:25]
    slides = [_coerce_slide(s if isinstance(s, dict) else {}, i, len(slides_raw)) for i, s in enumerate(slides_raw)]
    dp = canonical_preset_id(str(data.get("design_preset") or "fresh"))
    merged = normalize_plan_palette({"design_preset": dp, "palette": data.get("palette")})
    return PresentationPlan(
        title=str(data.get("title", "")).strip() or "Без названия",
        subtitle=str(data.get("subtitle", "")).strip(),
        theme=str(data.get("theme", "")).strip() or "general",
        palette=merged,
        slides=slides,
        design_preset=dp,
    )


async def _self_check_plan(
    client: AIClient,
    plan_dict: dict[str, Any],
    *,
    user_prompt: str,
    text_density: TextDensity,
    language: str,
) -> dict[str, Any]:
    """Прогоняет план через LLM повторно: факт-чек, плотность, повторы.

    Возвращает исправленный JSON в той же схеме. Никогда не падает наружу:
    при любой ошибке возвращает исходный план без изменений.
    """
    spec = _DENSITY_RULES.get(text_density, _DENSITY_RULES["balanced"])
    review_prompt = f"""Ты — строгий редактор-факт-чекер презентации.
Тебе дан JSON структуры презентации. Сделай тщательный РЕВЬЮ и ИСПРАВЬ:

1) ФАКТЫ. Найди фактические ошибки, неточности и сомнительные утверждения. Если ты не уверен в цифре,
   дате, имени или названии — замени на обобщение или удали. Не выдумывай.
2) ПРОТИВОРЕЧИЯ. Удали слайды/буллеты, которые противоречат другим слайдам того же плана.
3) ПОВТОРЫ. Удали дубли смысла между слайдами; перефразируй так, чтобы каждый слайд давал новое.
4) ПЛОТНОСТЬ — «{spec['label']}». СТРОГО: {spec['rule']}.
   Если буллетов слишком много — оставь самые важные. Если слишком длинные — сократи.
5) ЗАГОЛОВКИ — короткие (до 60 символов), без точки в конце.
6) СТРУКТУРА — сохрани тот же набор и порядок kind у слайдов и общее их количество.
7) ЯЗЫК — {language}.
8) Поля image_prompt и image_data_url НЕ меняй (оставь как есть).
9) ТАБЛИЦЫ (kind="table"). Проверь поля headers и rows:
   - все строки rows имеют ту же длину, что и headers;
   - в ячейках нет выдуманных конкретных чисел/дат/имён, в которых ты не уверен — замени на «—» или обобщение;
   - не должно быть пустых столбцов и полностью пустых строк;
   - заголовки колонок короткие (1–3 слова), ячейки короткие (до 6 слов).
   Если table-слайд осмыслен — оставь его как table и поправь ячейки. Не превращай table в content.

Исходная тема пользователя: «{user_prompt}»

Текущий план (JSON):
{json.dumps(plan_dict, ensure_ascii=False)}

Верни ТОЛЬКО валидный JSON в той же схеме, без пояснений и без markdown-обёртки.
"""
    try:
        raw = await client.chat(
            review_prompt,
            system_prompt=(
                "Ты возвращаешь СТРОГО валидный JSON в той же схеме, что и на входе. "
                "Никаких комментариев, никакого текста до или после JSON."
            ),
            max_new_tokens=4096,
            temperature=0.15,
        )
        fixed = _extract_json(raw)
    except Exception:
        logger.exception("self-check failed, keeping original plan")
        return plan_dict

    if not isinstance(fixed, dict) or not isinstance(fixed.get("slides"), list) or not fixed["slides"]:
        return plan_dict
    if len(fixed["slides"]) != len(plan_dict.get("slides", [])):
        # Не разрешаем удалять/добавлять слайды на этапе ревью.
        logger.warning(
            "self-check changed slide count (%d -> %d), discarding",
            len(plan_dict.get("slides", [])),
            len(fixed["slides"]),
        )
        return plan_dict

    # Сохраняем image_data_url исходного плана (модель могла его выкинуть).
    src_slides = plan_dict.get("slides") or []
    for i, s in enumerate(fixed["slides"]):
        if not isinstance(s, dict):
            continue
        if i < len(src_slides) and isinstance(src_slides[i], dict):
            url = str(src_slides[i].get("image_data_url", "")).strip()
            if url:
                s["image_data_url"] = url
            if not s.get("image_prompt"):
                s["image_prompt"] = src_slides[i].get("image_prompt", "")

    if not fixed.get("palette") and plan_dict.get("palette"):
        fixed["palette"] = plan_dict["palette"]
    if not fixed.get("title") and plan_dict.get("title"):
        fixed["title"] = plan_dict["title"]
    if not fixed.get("subtitle") and plan_dict.get("subtitle"):
        fixed["subtitle"] = plan_dict["subtitle"]
    if not fixed.get("theme") and plan_dict.get("theme"):
        fixed["theme"] = plan_dict["theme"]
    if fixed.get("design_preset") is None and plan_dict.get("design_preset"):
        fixed["design_preset"] = plan_dict["design_preset"]
    return fixed


async def plan_presentation(
    client: AIClient,
    user_prompt: str,
    n_slides: int,
    text_density: TextDensity = "balanced",
    images_mode: ImagesMode = "with-images",
    self_check: bool = True,
    design_preset: str = DEFAULT_PRESET,
) -> PresentationPlan:
    """Сгенерировать план презентации через LLM."""
    n_slides = max(3, min(int(n_slides), 25))
    language = _detect_language(user_prompt)
    dp = canonical_preset_id(design_preset)
    preset_label = PRESET_LABELS_RU.get(dp, dp)
    prompt = _build_prompt(
        user_prompt, n_slides, text_density, images_mode, language, preset_label=preset_label
    )

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
        data["slides"] = slides_raw

    if self_check:
        data = await _self_check_plan(
            client,
            data,
            user_prompt=user_prompt,
            text_density=text_density,
            language=language,
        )
        slides_raw = data.get("slides") or slides_raw

    slides = [_coerce_slide(s, i, len(slides_raw)) for i, s in enumerate(slides_raw)]

    if images_mode == "no-images":
        for s in slides:
            s.image_prompt = ""

    merged_palette = normalize_plan_palette({"design_preset": dp, "palette": data.get("palette")})
    return PresentationPlan(
        title=str(data.get("title", "")).strip() or "Без названия",
        subtitle=str(data.get("subtitle", "")).strip(),
        theme=str(data.get("theme", "")).strip() or "general",
        palette=merged_palette,
        slides=slides,
        design_preset=dp,
    )


def _build_sample_prompt(
    user_prompt: str,
    sample: SampleAnalysis,
    n_slides: int,
    images_mode: ImagesMode,
    language: str,
    text_density: TextDensity | None = None,
    *,
    preset_label: str = "",
) -> str:
    images_hint = (
        "Для каждого контентного слайда придумай поле image_prompt — короткое описание "
        "иллюстрации на английском языке (без текста на изображении), подходящей по смыслу."
        if images_mode == "with-images"
        else "Поле image_prompt оставляй пустой строкой."
    )
    density_label: TextDensity = text_density or sample.density  # type: ignore[assignment]
    if density_label not in _DENSITY_RULES:
        density_label = "balanced"
    density_block = _density_block(density_label)

    sample_json = sample_outline_for_llm(sample)

    schema = {
        "title": "string",
        "subtitle": "string",
        "theme": "string",
        "palette": {
            "primary": "#RRGGBB",
            "accent": "#RRGGBB",
            "background": "#RRGGBB",
            "text": "#RRGGBB",
            "muted": "#RRGGBB",
        },
        "slides": [
            {
                "kind": "title|content|two_column|section|conclusion|table",
                "title": "string",
                "subtitle": "string (опционально)",
                "bullets": ["string", "..."],
                "body": "string (опционально)",
                "image_prompt": "string",
                "notes": "string (опционально)",
                "headers": ["string (только для kind=table)"],
                "rows": [["string", "..."]],
            }
        ],
    }

    return f"""Тебе дан образец чужой презентации (структура + палитра + плотность текста).
Создай НОВУЮ презентацию на тему пользователя в ПОХОЖЕМ стиле и с похожей структурой.

Образец (JSON):
{sample_json}

Что нужно унаследовать от образца:
- ту же или близкую цветовую палитру (используй palette из образца, можешь чуть-чуть откорректировать для гармонии);
- тот же ритм слайдов (последовательность kind: title → ... → conclusion);
- стиль заголовков (длина, тон, эмоциональность).

{density_block}

Что менять:
- содержание полностью переписать под новую тему пользователя;
- бюджет: ровно {n_slides} слайдов;
- язык контента — {language}.

Дополнительные требования:
- ФАКТЫ: если не уверен в конкретной цифре/дате/имени — не пиши её, давай обобщение.
- Не повторяйся между слайдами и не противоречь сам себе.
- Заголовки — короткие (до 60 символов), без точки в конце.
- ТАБЛИЦА: если тема нуждается в сравнении/спецификации/тарифе/расписании/статистике, добавь
  1–2 слайда kind="table" с headers (2–5 шт.) и rows (2–7 шт.); ячейки короткие, без выдуманных
  чисел (лучше пусто, чем неправда).

Тема пользователя: «{user_prompt}»

Выбранный визуальный пресент оформления (финальные цвета в экспорте): {preset_label or "по умолчанию"}

{images_hint}

Верни СТРОГО валидный JSON без markdown-обёртки следующей формы:
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""


async def plan_presentation_from_sample(
    client: AIClient,
    user_prompt: str,
    sample: SampleAnalysis,
    n_slides: int | None = None,
    images_mode: ImagesMode = "with-images",
    text_density: TextDensity | None = None,
    self_check: bool = True,
    design_preset: str = DEFAULT_PRESET,
) -> PresentationPlan:
    """Сгенерировать план в стиле образца."""
    target_n = int(n_slides) if n_slides else sample.n_slides
    target_n = max(3, min(target_n, 25))
    language = _detect_language(user_prompt)
    dp = canonical_preset_id(design_preset)
    preset_label = PRESET_LABELS_RU.get(dp, dp)

    prompt = _build_sample_prompt(
        user_prompt=user_prompt,
        sample=sample,
        n_slides=target_n,
        images_mode=images_mode,
        language=language,
        text_density=text_density,
        preset_label=preset_label,
    )

    raw = await client.chat(
        prompt,
        system_prompt=(
            "Ты возвращаешь СТРОГО валидный JSON без пояснений и без markdown-обёртки."
        ),
        max_new_tokens=4096,
        temperature=0.5,
    )

    try:
        data = _extract_json(raw)
    except Exception:
        logger.exception("LLM вернула невалидный JSON, делаю ретрай")
        raw = await client.chat(
            prompt + "\n\nВНИМАНИЕ: ответ должен быть только JSON.",
            system_prompt="Возвращай только валидный JSON.",
            max_new_tokens=4096,
            temperature=0.2,
        )
        data = _extract_json(raw)

    slides_raw = data.get("slides") or []
    if not isinstance(slides_raw, list) or not slides_raw:
        raise ValueError("LLM вернула пустой массив slides")

    if len(slides_raw) > target_n:
        slides_raw = slides_raw[:target_n]
        data["slides"] = slides_raw

    effective_density: TextDensity = text_density or "balanced"  # type: ignore[assignment]
    if effective_density not in _DENSITY_RULES:
        effective_density = "balanced"

    if self_check:
        data = await _self_check_plan(
            client,
            data,
            user_prompt=user_prompt,
            text_density=effective_density,
            language=language,
        )
        slides_raw = data.get("slides") or slides_raw

    slides = [_coerce_slide(s, i, len(slides_raw)) for i, s in enumerate(slides_raw)]

    if images_mode == "no-images":
        for s in slides:
            s.image_prompt = ""

    seed_palette = data.get("palette")
    if not isinstance(seed_palette, dict) or len(seed_palette) < 2:
        seed_palette = dict(sample.palette)
    merged = normalize_plan_palette({"design_preset": dp, "palette": seed_palette})

    return PresentationPlan(
        title=str(data.get("title", "")).strip() or sample.title_guess or "Без названия",
        subtitle=str(data.get("subtitle", "")).strip(),
        theme=str(data.get("theme", "")).strip() or "from_sample",
        palette=merged,
        slides=slides,
        design_preset=dp,
    )


async def regenerate_slide(
    client: AIClient,
    *,
    plan: PresentationPlan,
    slide_index: int,
    instruction: str,
    images_mode: ImagesMode = "with-images",
) -> SlideSpec:
    """Regenerate a single slide while keeping consistency with the deck."""
    if slide_index < 0 or slide_index >= len(plan.slides):
        raise ValueError("slide_index out of range")

    current = plan.slides[slide_index]
    outline = [
        {"n": i + 1, "kind": s.kind, "title": s.title}
        for i, s in enumerate(plan.slides)
    ]
    schema = {
        "kind": "title|content|two_column|section|conclusion|table",
        "title": "string",
        "subtitle": "string",
        "bullets": ["string", "..."],
        "body": "string",
        "image_prompt": "string",
        "notes": "string",
        "headers": ["string (только если kind=table)"],
        "rows": [["string", "..."]],
    }
    table_hint = ""
    if current.kind == "table":
        table_hint = (
            "\nЭто табличный слайд. Сохрани kind=\"table\". В headers оставь 2–5 коротких заголовков, "
            "в rows — 2–7 строк ровно той же длины, что и headers. "
            "Не выдумывай числа: если не уверен — ставь «—». Поля bullets/body на этом слайде должны быть пустыми."
        )

    prompt = f"""Ты редактор презентаций.
Презентация:
- title: {plan.title}
- subtitle: {plan.subtitle}
- theme: {plan.theme}
- outline: {json.dumps(outline, ensure_ascii=False)}

Нужно перегенерировать только слайд №{slide_index + 1}.
Инструкция пользователя:
«{instruction}»

Текущий слайд:
{json.dumps(current.to_dict(), ensure_ascii=False)}

Требования:
1) Сохрани стиль и логику всей презентации.
2) Предпочтительно сохрани kind текущего слайда: {current.kind}.
3) Не выдумывай факты — если не уверен в цифре/имени, замени на обобщение.
4) Верни только JSON одного слайда без markdown.{table_hint}
5) Формат:
{json.dumps(schema, ensure_ascii=False, indent=2)}
"""
    raw = await client.chat(
        prompt,
        system_prompt="Возвращай только валидный JSON без пояснений.",
        max_new_tokens=1800,
        temperature=0.45,
    )
    data = _extract_json(raw)
    if isinstance(data, dict) and "slide" in data and isinstance(data["slide"], dict):
        data = data["slide"]
    slide = _coerce_slide(data if isinstance(data, dict) else {}, slide_index, len(plan.slides))
    if not slide.title:
        slide.title = current.title
    slide.kind = current.kind
    slide.image_data_url = current.image_data_url
    slide.style = {**dict(current.style), **dict(slide.style)}
    slide.image_placement = current.image_placement
    if current.kind == "table" and not (slide.headers and slide.rows):
        slide.headers = list(current.headers)
        slide.rows = [list(r) for r in current.rows]
    if images_mode == "no-images":
        slide.image_prompt = ""
    return slide
