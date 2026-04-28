"""Анализ существующей презентации (PPTX или PDF) для извлечения стиля.

Возвращает SampleAnalysis: количество слайдов, оценка плотности текста,
извлечённая цветовая палитра, типы слайдов и краткое содержание.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pptx import Presentation
from pptx.util import Emu

logger = logging.getLogger(__name__)

SourceFormat = Literal["pptx", "pdf"]


@dataclass
class SampleSlideInfo:
    title: str = ""
    bullets: list[str] = field(default_factory=list)
    body: str = ""
    word_count: int = 0
    has_image: bool = False
    kind_guess: str = "content"  # title | content | section | conclusion

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SampleAnalysis:
    sample_id: str
    source_format: SourceFormat
    file_name: str
    n_slides: int
    palette: dict[str, str]
    density: str  # minimal | balanced | detailed
    has_images: bool
    slides: list[SampleSlideInfo]
    title_guess: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "source_format": self.source_format,
            "file_name": self.file_name,
            "n_slides": self.n_slides,
            "palette": self.palette,
            "density": self.density,
            "has_images": self.has_images,
            "title_guess": self.title_guess,
            "slides": [s.to_dict() for s in self.slides],
        }

    def short_summary(self) -> dict[str, Any]:
        """Компактная сводка для UI (без полных текстов)."""
        return {
            "sample_id": self.sample_id,
            "source_format": self.source_format,
            "file_name": self.file_name,
            "n_slides": self.n_slides,
            "palette": self.palette,
            "density": self.density,
            "has_images": self.has_images,
            "title_guess": self.title_guess,
            "outline": [
                {
                    "title": s.title[:80],
                    "kind": s.kind_guess,
                    "bullets": len(s.bullets),
                    "has_image": s.has_image,
                }
                for s in self.slides
            ],
        }


_DEFAULT_PALETTE = {
    "primary": "#1F2937",
    "accent": "#6366F1",
    "background": "#FFFFFF",
    "text": "#111827",
    "muted": "#6B7280",
}


def _density_from_words(avg_words: float) -> str:
    if avg_words < 18:
        return "minimal"
    if avg_words < 50:
        return "balanced"
    return "detailed"


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex_to_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*rgb)


def _palette_from_counts(counter: Counter[tuple[int, int, int]]) -> dict[str, str]:
    """Из набора цветов собираем согласованную палитру."""
    if not counter:
        return dict(_DEFAULT_PALETTE)

    candidates = [rgb for rgb, _ in counter.most_common(20)]
    candidates.sort(key=_luminance)

    bg = candidates[-1]
    text = candidates[0]
    if _luminance(bg) - _luminance(text) < 0.4:
        bg = (255, 255, 255)
        text = (17, 24, 39)

    middles = [c for c in candidates if c not in (bg, text)]
    accent = next(
        (
            c
            for c in middles
            if 0.18 < _luminance(c) < 0.78
            and (max(c) - min(c)) > 25
        ),
        (99, 102, 241),
    )
    primary = next(
        (c for c in middles if c not in (accent,) and _luminance(c) < 0.45),
        (31, 41, 55),
    )
    muted = next(
        (
            c
            for c in middles
            if c not in (accent, primary) and 0.30 < _luminance(c) < 0.70
        ),
        (107, 114, 128),
    )

    return {
        "primary": _rgb_to_hex(primary),
        "accent": _rgb_to_hex(accent),
        "background": _rgb_to_hex(bg),
        "text": _rgb_to_hex(text),
        "muted": _rgb_to_hex(muted),
    }


def _guess_kind(idx: int, total: int, info: SampleSlideInfo) -> str:
    if idx == 0:
        return "title"
    if idx == total - 1 and re.search(
        r"(вывод|итог|заключени|conclusion|summary|спасибо|thank)",
        (info.title + " " + info.body).lower(),
    ):
        return "conclusion"
    if idx == total - 1:
        return "conclusion"
    if not info.bullets and len(info.body) < 60 and info.word_count <= 8:
        return "section"
    return "content"


# ============================ PPTX ============================
def _extract_pptx_palette(prs: Presentation) -> Counter[tuple[int, int, int]]:
    counter: Counter[tuple[int, int, int]] = Counter()

    for slide in prs.slides:
        for shape in slide.shapes:
            try:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        for run in para.runs:
                            try:
                                color = run.font.color
                                rgb = getattr(color, "rgb", None)
                                if rgb is not None:
                                    counter[(rgb[0], rgb[1], rgb[2])] += 2
                            except Exception:
                                pass
            except Exception:
                pass
            try:
                fill = getattr(shape, "fill", None)
                if fill and getattr(fill, "type", None) == 1:
                    rgb = fill.fore_color.rgb
                    if rgb is not None:
                        counter[(rgb[0], rgb[1], rgb[2])] += 1
            except Exception:
                pass
    return counter


def _extract_pptx_slide(slide) -> SampleSlideInfo:
    title = ""
    bullets: list[str] = []
    body_parts: list[str] = []
    has_image = False

    for shape in slide.shapes:
        try:
            shape_type_name = type(shape).__name__.lower()
            if "picture" in shape_type_name or getattr(shape, "shape_type", None) == 13:
                has_image = True
        except Exception:
            pass

        try:
            if shape.has_text_frame:
                texts = [p.text.strip() for p in shape.text_frame.paragraphs]
                texts = [t for t in texts if t]
                if not texts:
                    continue
                is_title = False
                try:
                    ph = getattr(shape, "placeholder_format", None)
                    if ph is not None and ph.idx in (0, 13):
                        is_title = True
                except Exception:
                    pass
                if not title and is_title:
                    title = texts[0]
                    if len(texts) > 1:
                        body_parts.extend(texts[1:])
                else:
                    if len(texts) > 1 or (
                        texts and len(texts[0]) > 0 and (
                            texts[0].startswith(("•", "-", "·", "●", "*"))
                            or len(texts) >= 2
                        )
                    ):
                        for t in texts:
                            cleaned = t.lstrip("•-·●*— ").strip()
                            if cleaned:
                                if 2 <= len(cleaned.split()) <= 30:
                                    bullets.append(cleaned)
                                else:
                                    body_parts.append(cleaned)
                    else:
                        body_parts.extend(texts)
        except Exception:
            continue

    if not title and body_parts:
        first = body_parts[0]
        if len(first) <= 100:
            title = first
            body_parts = body_parts[1:]

    body = " ".join(body_parts).strip()
    info = SampleSlideInfo(
        title=title,
        bullets=bullets[:10],
        body=body[:600],
        word_count=len((title + " " + body + " " + " ".join(bullets)).split()),
        has_image=has_image,
    )
    return info


def analyze_pptx(path: Path, sample_id: str) -> SampleAnalysis:
    prs = Presentation(str(path))
    slides: list[SampleSlideInfo] = []
    for slide in prs.slides:
        slides.append(_extract_pptx_slide(slide))
    n = len(slides)
    for i, info in enumerate(slides):
        info.kind_guess = _guess_kind(i, n, info)

    palette_counter = _extract_pptx_palette(prs)
    palette = _palette_from_counts(palette_counter)

    avg_words = sum(s.word_count for s in slides) / max(1, n)
    density = _density_from_words(avg_words)
    has_images = any(s.has_image for s in slides)
    title_guess = slides[0].title if slides else ""

    return SampleAnalysis(
        sample_id=sample_id,
        source_format="pptx",
        file_name=path.name,
        n_slides=n,
        palette=palette,
        density=density,
        has_images=has_images,
        slides=slides,
        title_guess=title_guess,
    )


# ============================ PDF ============================
def _split_pdf_page_text(text: str) -> tuple[str, list[str], str]:
    """Эвристика: первая короткая строка = заголовок.

    Дальше — буллеты (короткие/со маркерами) или body (длинный текст)."""
    raw_lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln.strip() for ln in raw_lines if ln.strip()]
    if not lines:
        return "", [], ""

    title = ""
    body_lines: list[str] = []
    bullets: list[str] = []

    if len(lines[0]) <= 90:
        title = lines[0]
        rest = lines[1:]
    else:
        rest = lines

    bullet_re = re.compile(r"^[\-\*\u2022\u00b7\u25cf\u25e6\u2013\u2014\u2192]\s+")
    for ln in rest:
        if bullet_re.match(ln):
            cleaned = bullet_re.sub("", ln).strip()
            if cleaned:
                bullets.append(cleaned)
        elif 2 <= len(ln.split()) <= 25 and not ln.endswith(".") and len(rest) > 1:
            bullets.append(ln)
        else:
            body_lines.append(ln)

    body = " ".join(body_lines).strip()
    if not bullets and body:
        sentences = re.split(r"(?<=[.!?])\s+", body)
        if len(sentences) >= 3:
            bullets = [s.strip() for s in sentences[:6] if 3 <= len(s.split()) <= 25]
            if bullets:
                body = ""

    return title, bullets[:10], body[:600]


def analyze_pdf(path: Path, sample_id: str) -> SampleAnalysis:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    slides: list[SampleSlideInfo] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        title, bullets, body = _split_pdf_page_text(text)
        info = SampleSlideInfo(
            title=title,
            bullets=bullets,
            body=body,
            word_count=len((title + " " + body + " " + " ".join(bullets)).split()),
            has_image=False,
        )
        slides.append(info)

    n = len(slides) or 1
    for i, info in enumerate(slides):
        info.kind_guess = _guess_kind(i, n, info)

    avg_words = sum(s.word_count for s in slides) / max(1, n)
    density = _density_from_words(avg_words)
    title_guess = slides[0].title if slides else ""

    return SampleAnalysis(
        sample_id=sample_id,
        source_format="pdf",
        file_name=path.name,
        n_slides=n,
        palette=dict(_DEFAULT_PALETTE),  # из PDF цвета по тексту извлечь надёжно нельзя
        density=density,
        has_images=False,
        slides=slides,
        title_guess=title_guess,
    )


# ============================ entry ============================
def analyze_file(path: Path, sample_id: str) -> SampleAnalysis:
    suffix = path.suffix.lower()
    if suffix == ".pptx":
        return analyze_pptx(path, sample_id)
    if suffix == ".pdf":
        return analyze_pdf(path, sample_id)
    raise ValueError(f"Неподдерживаемый формат: {suffix}. Используйте .pptx или .pdf")


def sample_outline_for_llm(sample: SampleAnalysis, max_chars: int = 4000) -> str:
    """Готовим компактный JSON-блок для подсказки LLM."""
    payload = {
        "n_slides": sample.n_slides,
        "density": sample.density,
        "palette": sample.palette,
        "has_images": sample.has_images,
        "title_guess": sample.title_guess,
        "slides": [
            {
                "kind": s.kind_guess,
                "title": s.title[:90],
                "bullets": [b[:120] for b in s.bullets[:6]],
                "body": s.body[:240],
            }
            for s in sample.slides
        ],
    }
    text = json.dumps(payload, ensure_ascii=False)
    if len(text) > max_chars:
        compact = {
            "n_slides": sample.n_slides,
            "density": sample.density,
            "palette": sample.palette,
            "has_images": sample.has_images,
            "title_guess": sample.title_guess,
            "slides": [
                {"kind": s.kind_guess, "title": s.title[:80]}
                for s in sample.slides
            ],
        }
        text = json.dumps(compact, ensure_ascii=False)
    return text
