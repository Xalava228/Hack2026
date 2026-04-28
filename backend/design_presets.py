"""Пресеты оформления презентации: палитра + ключ для рендеринга PPTX/PDF."""
from __future__ import annotations

from typing import Any, Literal

DesignPresetId = Literal[
    "fresh",
    "ocean",
    "sunrise",
    "midnight",
    "pastel",
    "forest",
]


# Полная палитра на слайде: primary=заголовки, accent/secondary=акценты, bg, surface — карточки
PRESET_PALETTES: dict[str, dict[str, str]] = {
    "fresh": {
        "primary": "#1E293B",
        "accent": "#6366F1",
        "accent2": "#8B5CF6",
        "background": "#F1F5F9",
        "surface": "#FFFFFF",
        "text": "#334155",
        "muted": "#64748B",
    },
    "ocean": {
        "primary": "#0C4A6E",
        "accent": "#0284C7",
        "accent2": "#38BDF8",
        "background": "#F0F9FF",
        "surface": "#FFFFFF",
        "text": "#164E63",
        "muted": "#0E7490",
    },
    "sunrise": {
        "primary": "#BE123C",
        "accent": "#EA580C",
        "accent2": "#F59E0B",
        "background": "#FFF7ED",
        "surface": "#FFFFFF",
        "text": "#9A3412",
        "muted": "#C2410C",
    },
    "midnight": {
        "primary": "#F8FAFC",
        "accent": "#38BDF8",
        "accent2": "#818CF8",
        "background": "#0F172A",
        "surface": "#1E293B",
        "text": "#E2E8F0",
        "muted": "#94A3B8",
    },
    "pastel": {
        "primary": "#581C87",
        "accent": "#C084FC",
        "accent2": "#E879F9",
        "background": "#FAF5FF",
        "surface": "#FFFFFF",
        "text": "#4C1D95",
        "muted": "#7C3AED",
    },
    "forest": {
        "primary": "#14532D",
        "accent": "#16A34A",
        "accent2": "#4ADE80",
        "background": "#F7FEE7",
        "surface": "#FFFFFF",
        "text": "#166534",
        "muted": "#3F6212",
    },
}

PRESET_LABELS_RU: dict[str, str] = {
    "fresh": "Свежее (slate / indigo)",
    "ocean": "Океан (голубой)",
    "sunrise": "Рассвет (оранж / розовый)",
    "midnight": "Полночь (тёмный)",
    "pastel": "Пастель (лаванда)",
    "forest": "Лес (зелёный)",
}

PRESET_STYLE_TOKENS: dict[str, dict[str, str | float]] = {
    "fresh": {
        "title_font": "Calibri",
        "body_font": "Calibri",
        "title_scale": 1.0,
        "body_scale": 1.0,
        "underline_ratio": 0.09,
        "layout": "clean",
    },
    "ocean": {
        "title_font": "Segoe UI Semibold",
        "body_font": "Segoe UI",
        "title_scale": 1.02,
        "body_scale": 1.0,
        "underline_ratio": 0.12,
        "layout": "split",
    },
    "sunrise": {
        "title_font": "Trebuchet MS",
        "body_font": "Verdana",
        "title_scale": 1.04,
        "body_scale": 0.98,
        "underline_ratio": 0.1,
        "layout": "cards",
    },
    "midnight": {
        "title_font": "Bahnschrift SemiBold",
        "body_font": "Bahnschrift",
        "title_scale": 1.03,
        "body_scale": 1.02,
        "underline_ratio": 0.14,
        "layout": "bold",
    },
    "pastel": {
        "title_font": "Candara Bold",
        "body_font": "Candara",
        "title_scale": 1.02,
        "body_scale": 1.0,
        "underline_ratio": 0.11,
        "layout": "cards",
    },
    "forest": {
        "title_font": "Cambria Bold",
        "body_font": "Cambria",
        "title_scale": 1.0,
        "body_scale": 1.0,
        "underline_ratio": 0.08,
        "layout": "clean",
    },
}

VALID_PRESETS: frozenset[str] = frozenset(PRESET_PALETTES.keys())

DEFAULT_PRESET: DesignPresetId = "fresh"


def canonical_preset_id(pid: str) -> str:
    p = pid.strip().lower()
    return p if p in PRESET_PALETTES else DEFAULT_PRESET

_DEFAULT_FULL: dict[str, str] = {
    **PRESET_PALETTES[DEFAULT_PRESET],
}


def palette_for_preset(preset_id: str) -> dict[str, str]:
    """Палитра по id пресета (или дефолт)."""
    pid = preset_id.strip().lower()
    base = PRESET_PALETTES.get(pid)
    if not base:
        return dict(_DEFAULT_FULL)
    return {**base}


def _normalize_hex(raw: Any, fallback: str) -> str:
    s = str(raw or "").strip()
    if not s:
        return fallback
    s = s.replace("#", "")
    if len(s) != 6:
        return fallback
    try:
        int(s, 16)
    except ValueError:
        return fallback
    return "#" + s.upper()


def normalize_plan_palette(plan_dict: dict[str, Any]) -> dict[str, str]:
    """Базируемся на палитре пресета и подмешиваем hex из plan.palette (ред. / от LLM)."""
    preset_id = str(plan_dict.get("design_preset") or DEFAULT_PRESET)
    merged = palette_for_preset(preset_id)
    raw = plan_dict.get("palette")
    if isinstance(raw, dict):
        for key in merged.keys():
            if key in raw:
                merged[key] = _normalize_hex(raw.get(key), merged[key])
        for k, v in raw.items():
            if k not in merged and isinstance(v, str) and len(v.strip()) >= 4:
                norm = _normalize_hex(v, "")
                if len(norm) == 7:
                    merged[str(k)] = norm
    return merged


def merge_slide_palette(plan_palette: dict[str, str], slide_style: dict[str, str]) -> dict[str, str]:
    """Объединить палитру плана со стилевыми переопределениями слайда."""
    out = dict(plan_palette)
    if not slide_style:
        return out
    key_map = {
        "primary": "primary",
        "accent": "accent",
        "accent2": "accent2",
        "background": "background",
        "surface": "surface",
        "text": "text",
        "muted": "muted",
        "bg": "background",
        "title_color": "primary",
        "body_color": "text",
    }
    for k, v in slide_style.items():
        target = key_map.get(k, k if k in out else "")
        if not target:
            continue
        cur = out.get(target, "#000000")
        normed = _normalize_hex(v, cur)
        if len(normed) == 7:
            out[target] = normed
    return out


def coerce_hex(value: Any, fallback: str) -> str:
    """Публичный хелпер: нормализовать hex или вернуть fallback."""
    fb = fallback if fallback.startswith("#") else "#" + fallback.replace("#", "")
    if len(fb) != 7:
        fb = "#FFFFFF"
    return _normalize_hex(value, fb)


def style_for_preset(preset_id: str) -> dict[str, str | float]:
    pid = canonical_preset_id(preset_id)
    base = PRESET_STYLE_TOKENS.get(DEFAULT_PRESET, {})
    cur = PRESET_STYLE_TOKENS.get(pid, {})
    return {**base, **cur}
