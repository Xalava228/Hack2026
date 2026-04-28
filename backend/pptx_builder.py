"""Сборка PPTX по плану презентации.

Все слайды рендерятся через python-pptx с кастомным цветовым оформлением,
без зависимости от шаблонов PowerPoint.
"""
from __future__ import annotations

import io
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

from .slide_planner import PresentationPlan, SlideSpec

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


def _hex(value: str) -> RGBColor:
    v = value.lstrip("#")
    if len(v) != 6:
        v = "111827"
    return RGBColor(int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def _set_solid_fill(shape, color: str) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _hex(color)
    shape.line.fill.background()


def _add_background(slide, color: str) -> None:
    rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    _set_solid_fill(rect, color)
    rect.shadow.inherit = False


def _add_accent_bar(slide, color: str, x=0, y=0, w=Inches(0.18), h=SLIDE_H) -> None:
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    _set_solid_fill(bar, color)


def _add_textbox(
    slide,
    left,
    top,
    width,
    height,
    text: str,
    *,
    color: str,
    size: int,
    bold: bool = False,
    align: str = "left",
) -> None:
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    p = tf.paragraphs[0]
    p.alignment = {
        "left": PP_ALIGN.LEFT,
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
    }.get(align, PP_ALIGN.LEFT)
    run = p.add_run()
    run.text = text
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = _hex(color)


def _add_bullets(
    slide,
    left,
    top,
    width,
    height,
    bullets: list[str],
    *,
    color: str,
    accent: str,
    size: int = 20,
) -> None:
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0)
    tf.margin_right = Inches(0)
    tf.margin_top = Inches(0)
    tf.margin_bottom = Inches(0)
    for i, item in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = PP_ALIGN.LEFT
        p.space_after = Pt(8)

        marker = p.add_run()
        marker.text = "●  "
        marker.font.name = "Calibri"
        marker.font.size = Pt(size)
        marker.font.bold = True
        marker.font.color.rgb = _hex(accent)

        run = p.add_run()
        run.text = item
        run.font.name = "Calibri"
        run.font.size = Pt(size)
        run.font.color.rgb = _hex(color)


def _add_image(slide, image_bytes: bytes, left, top, width, height) -> None:
    bio = io.BytesIO(image_bytes)
    pic = slide.shapes.add_picture(bio, left, top, width=width, height=height)
    pic.shadow.inherit = False


def _render_title(prs: Presentation, plan: PresentationPlan, spec: SlideSpec) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _add_background(slide, plan.palette["background"])
    _add_accent_bar(slide, plan.palette["accent"], 0, 0, SLIDE_W, Inches(0.25))
    _add_accent_bar(
        slide, plan.palette["accent"], 0, SLIDE_H - Inches(0.25), SLIDE_W, Inches(0.25)
    )

    _add_textbox(
        slide,
        Inches(0.9),
        Inches(2.4),
        SLIDE_W - Inches(1.8),
        Inches(2.0),
        spec.title or plan.title,
        color=plan.palette["primary"],
        size=54,
        bold=True,
        align="center",
    )
    if spec.subtitle or plan.subtitle:
        _add_textbox(
            slide,
            Inches(0.9),
            Inches(4.4),
            SLIDE_W - Inches(1.8),
            Inches(1.2),
            spec.subtitle or plan.subtitle,
            color=plan.palette["muted"],
            size=24,
            align="center",
        )


def _render_section(prs: Presentation, plan: PresentationPlan, spec: SlideSpec) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _add_background(slide, plan.palette["primary"])
    _add_textbox(
        slide,
        Inches(1.0),
        Inches(3.0),
        SLIDE_W - Inches(2.0),
        Inches(1.6),
        spec.title,
        color=plan.palette["background"],
        size=48,
        bold=True,
        align="center",
    )
    if spec.subtitle:
        _add_textbox(
            slide,
            Inches(1.0),
            Inches(4.4),
            SLIDE_W - Inches(2.0),
            Inches(1.0),
            spec.subtitle,
            color=plan.palette["accent"],
            size=24,
            align="center",
        )


def _render_content(
    prs: Presentation,
    plan: PresentationPlan,
    spec: SlideSpec,
    image: bytes | None,
) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _add_background(slide, plan.palette["background"])
    _add_accent_bar(slide, plan.palette["accent"])

    title_left = Inches(0.7)
    title_top = Inches(0.5)
    _add_textbox(
        slide,
        title_left,
        title_top,
        SLIDE_W - Inches(1.4),
        Inches(0.9),
        spec.title,
        color=plan.palette["primary"],
        size=32,
        bold=True,
    )
    underline = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE,
        title_left,
        Inches(1.45),
        Inches(1.2),
        Emu(38100),
    )
    _set_solid_fill(underline, plan.palette["accent"])

    has_image = image is not None
    text_left = Inches(0.7)
    text_top = Inches(1.7)
    text_height = SLIDE_H - text_top - Inches(0.5)
    text_width = SLIDE_W - Inches(1.4)
    if has_image:
        text_width = Inches(6.4)

    if spec.bullets:
        _add_bullets(
            slide,
            text_left,
            text_top,
            text_width,
            text_height,
            spec.bullets,
            color=plan.palette["text"],
            accent=plan.palette["accent"],
            size=20,
        )
    elif spec.body:
        _add_textbox(
            slide,
            text_left,
            text_top,
            text_width,
            text_height,
            spec.body,
            color=plan.palette["text"],
            size=18,
        )

    if has_image:
        img_left = Inches(7.4)
        img_top = Inches(1.7)
        img_w = SLIDE_W - img_left - Inches(0.5)
        img_h = SLIDE_H - img_top - Inches(0.5)
        _add_image(slide, image, img_left, img_top, img_w, img_h)


def _render_two_column(
    prs: Presentation,
    plan: PresentationPlan,
    spec: SlideSpec,
    image: bytes | None,
) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _add_background(slide, plan.palette["background"])
    _add_accent_bar(slide, plan.palette["accent"])

    _add_textbox(
        slide,
        Inches(0.7),
        Inches(0.5),
        SLIDE_W - Inches(1.4),
        Inches(0.9),
        spec.title,
        color=plan.palette["primary"],
        size=32,
        bold=True,
    )

    half = (SLIDE_W - Inches(2.1)) / 2
    bullets = spec.bullets or []
    left_b = bullets[: max(1, len(bullets) // 2)] or bullets
    right_b = bullets[len(left_b) :]

    _add_bullets(
        slide,
        Inches(0.7),
        Inches(1.7),
        half,
        SLIDE_H - Inches(2.2),
        left_b,
        color=plan.palette["text"],
        accent=plan.palette["accent"],
        size=20,
    )
    if right_b:
        _add_bullets(
            slide,
            Inches(0.7) + half + Inches(0.7),
            Inches(1.7),
            half,
            SLIDE_H - Inches(2.2),
            right_b,
            color=plan.palette["text"],
            accent=plan.palette["accent"],
            size=20,
        )
    elif image is not None:
        _add_image(
            slide,
            image,
            Inches(0.7) + half + Inches(0.7),
            Inches(1.7),
            half,
            SLIDE_H - Inches(2.2),
        )


def _render_conclusion(
    prs: Presentation, plan: PresentationPlan, spec: SlideSpec
) -> None:
    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _add_background(slide, plan.palette["background"])
    _add_accent_bar(slide, plan.palette["accent"], 0, 0, SLIDE_W, Inches(0.25))

    _add_textbox(
        slide,
        Inches(0.9),
        Inches(0.9),
        SLIDE_W - Inches(1.8),
        Inches(1.2),
        spec.title or "Выводы",
        color=plan.palette["primary"],
        size=40,
        bold=True,
        align="center",
    )

    if spec.bullets:
        _add_bullets(
            slide,
            Inches(1.5),
            Inches(2.4),
            SLIDE_W - Inches(3.0),
            Inches(4.0),
            spec.bullets,
            color=plan.palette["text"],
            accent=plan.palette["accent"],
            size=22,
        )
    elif spec.body:
        _add_textbox(
            slide,
            Inches(1.5),
            Inches(2.4),
            SLIDE_W - Inches(3.0),
            Inches(4.0),
            spec.body,
            color=plan.palette["text"],
            size=22,
            align="center",
        )

    if spec.subtitle:
        _add_textbox(
            slide,
            Inches(0.9),
            SLIDE_H - Inches(1.0),
            SLIDE_W - Inches(1.8),
            Inches(0.6),
            spec.subtitle,
            color=plan.palette["muted"],
            size=18,
            align="center",
        )


def build_pptx(
    plan: PresentationPlan,
    images: dict[int, bytes],
    out_path: Path,
) -> Path:
    """Собрать PPTX. images — словарь {номер_слайда: bytes_картинки}."""
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    for idx, spec in enumerate(plan.slides):
        img = images.get(idx)
        if spec.kind == "title":
            _render_title(prs, plan, spec)
        elif spec.kind == "section":
            _render_section(prs, plan, spec)
        elif spec.kind == "two_column":
            _render_two_column(prs, plan, spec, img)
        elif spec.kind == "conclusion":
            _render_conclusion(prs, plan, spec)
        else:
            _render_content(prs, plan, spec, img)

        if spec.notes:
            slide = prs.slides[idx]
            slide.notes_slide.notes_text_frame.text = spec.notes

    prs.save(str(out_path))
    return out_path
