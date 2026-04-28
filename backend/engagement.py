"""Анализ вовлеченности слайдов ("Анти-Душнила")."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .slide_planner import PresentationPlan, SlideSpec


@dataclass
class SlideEngagement:
    slide_index: int
    title: str
    kind: str
    boredom_percent: int
    sleep_after_sec: int
    text_chars: int
    bullet_count: int
    avg_words_per_bullet: float
    table_cells: int
    has_visual: bool
    risk_level: str
    verdict: str
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slide_index": self.slide_index,
            "title": self.title,
            "kind": self.kind,
            "boredom_percent": self.boredom_percent,
            "sleep_after_sec": self.sleep_after_sec,
            "text_chars": self.text_chars,
            "bullet_count": self.bullet_count,
            "avg_words_per_bullet": round(self.avg_words_per_bullet, 1),
            "table_cells": self.table_cells,
            "has_visual": self.has_visual,
            "risk_level": self.risk_level,
            "verdict": self.verdict,
            "recommendations": list(self.recommendations),
        }


def _words_count(text: str) -> int:
    return len([w for w in text.replace("\n", " ").split(" ") if w.strip()])


def _risk_label(score: int) -> str:
    if score >= 75:
        return "critical"
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _verdict(score: int, sleep_after_sec: int) -> str:
    if score >= 75:
        return f"На этом слайде до 80% аудитории уснет через {sleep_after_sec} секунд."
    if score >= 55:
        return f"Внимание начнет падать уже через {sleep_after_sec} секунд."
    if score >= 35:
        return "Нормально, но можно сделать живее и короче."
    return "Слайд держит внимание аудитории."


def _reco(spec: SlideSpec, score: int, has_visual: bool, table_cells: int) -> list[str]:
    out: list[str] = []
    if score >= 55:
        out.append("Сократить текст: оставить 3–4 коротких тезиса вместо длинного блока.")
        out.append("Добавить интерактив: мини-опрос с поднятием руки или быстрый квиз.")
    if not has_visual and spec.kind in ("content", "two_column", "section"):
        out.append("Добавить визуал: фото/иконка/схема вместо части текста.")
    if table_cells >= 20:
        out.append("Упростить таблицу: оставить только ключевые метрики, остальное вынести в приложение.")
    if score >= 70:
        out.append("Заменить часть контента на демонстрацию: интерактивный опрос или 3D-модель процесса.")
    if spec.kind == "table":
        out.append("Подсветить 1–2 ключевые строки цветом и дать устный комментарий вместо полного чтения.")
    return out[:4]


def analyze_slide_engagement(spec: SlideSpec, idx: int) -> SlideEngagement:
    bullet_words = [_words_count(b) for b in (spec.bullets or [])]
    avg_words_per_bullet = (sum(bullet_words) / len(bullet_words)) if bullet_words else 0.0
    text_chars = len((spec.title or "").strip()) + len((spec.subtitle or "").strip()) + len((spec.body or "").strip())
    text_chars += sum(len((b or "").strip()) for b in (spec.bullets or []))
    table_cells = len(spec.headers or []) * len(spec.rows or [])
    has_visual = bool((spec.image_data_url or "").strip() or (spec.image_prompt or "").strip())

    # Базовый "скучный" риск от вида слайда.
    score = 8
    if spec.kind in ("content", "two_column"):
        score += 14
    elif spec.kind == "table":
        score += 24

    # Текстовая перегрузка.
    score += min(45, max(0, int((text_chars - 220) / 10)))
    score += max(0, len(spec.bullets or []) - 4) * 8
    score += max(0, int(avg_words_per_bullet - 10)) * 2
    if len((spec.body or "").strip()) > 320:
        score += 12

    # Таблицы особенно чувствительны к размеру.
    if table_cells > 0:
        score += min(28, int(table_cells * 1.4))

    # Визуал снижает скуку.
    if has_visual:
        score -= 12
    if spec.kind in ("title", "section", "conclusion"):
        score -= 8

    score = max(3, min(98, score))
    sleep_after_sec = max(6, 24 - score // 5)
    risk = _risk_label(score)
    verdict = _verdict(score, sleep_after_sec)
    recommendations = _reco(spec, score, has_visual, table_cells)

    return SlideEngagement(
        slide_index=idx,
        title=spec.title or f"Слайд {idx + 1}",
        kind=spec.kind,
        boredom_percent=score,
        sleep_after_sec=sleep_after_sec,
        text_chars=text_chars,
        bullet_count=len(spec.bullets or []),
        avg_words_per_bullet=avg_words_per_bullet,
        table_cells=table_cells,
        has_visual=has_visual,
        risk_level=risk,
        verdict=verdict,
        recommendations=recommendations,
    )


def analyze_plan_engagement(plan: PresentationPlan) -> dict[str, Any]:
    slides = [analyze_slide_engagement(s, i) for i, s in enumerate(plan.slides)]
    if not slides:
        return {"deck_score": 0, "critical_slides": 0, "high_slides": 0, "slides": []}

    deck_score = int(sum(s.boredom_percent for s in slides) / len(slides))
    critical_slides = sum(1 for s in slides if s.risk_level == "critical")
    high_slides = sum(1 for s in slides if s.risk_level in ("critical", "high"))
    top = sorted(slides, key=lambda x: x.boredom_percent, reverse=True)[:3]

    return {
        "deck_score": deck_score,
        "critical_slides": critical_slides,
        "high_slides": high_slides,
        "summary": (
            "Риск 'смерть через PowerPoint' высокий: переработайте самые тяжелые слайды."
            if deck_score >= 60
            else "Презентация в целом держит внимание, но есть точки для усиления."
        ),
        "top_risks": [s.to_dict() for s in top],
        "slides": [s.to_dict() for s in slides],
    }
