"""Сборка PDF-презентации напрямую через ReportLab.

Не зависит от установленного офиса / LibreOffice.
Каждый слайд рендерится в отдельную PDF-страницу 13.333" x 7.5".
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image as PILImage
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from .design_presets import merge_slide_palette
from .slide_planner import PresentationPlan, SlideSpec

PAGE_W = 13.333 * inch
PAGE_H = 7.5 * inch


def _pdf_pal(plan: PresentationPlan, spec: SlideSpec) -> dict[str, str]:
    return merge_slide_palette(plan.palette, getattr(spec, "style", None) or {})


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = (current + " " + w).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


_FONT_REGULAR = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"


def _try_register_unicode_fonts() -> None:
    """Подключаем DejaVu, если доступно — поддержка кириллицы."""
    global _FONT_REGULAR, _FONT_BOLD
    candidates = [
        ("DejaVuSans", "DejaVuSans-Bold", [
            "C:/Windows/Fonts/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ], [
            "C:/Windows/Fonts/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]),
        ("Arial", "Arial-Bold", [
            "C:/Windows/Fonts/arial.ttf",
        ], [
            "C:/Windows/Fonts/arialbd.ttf",
        ]),
    ]
    for reg_name, bold_name, reg_paths, bold_paths in candidates:
        reg_found = next((p for p in reg_paths if Path(p).exists()), None)
        bold_found = next((p for p in bold_paths if Path(p).exists()), None)
        if reg_found and bold_found:
            try:
                pdfmetrics.registerFont(TTFont(reg_name, reg_found))
                pdfmetrics.registerFont(TTFont(bold_name, bold_found))
                _FONT_REGULAR = reg_name
                _FONT_BOLD = bold_name
                return
            except Exception:
                continue


_try_register_unicode_fonts()


def _draw_filled_rect(c: canvas.Canvas, x, y, w, h, color: str) -> None:
    c.setFillColor(HexColor(color))
    c.rect(x, y, w, h, stroke=0, fill=1)


def _draw_text(
    c: canvas.Canvas,
    text: str,
    x,
    y,
    *,
    color: str,
    size: int,
    bold: bool = False,
    align: str = "left",
    max_width: float | None = None,
) -> float:
    c.setFillColor(HexColor(color))
    font = _FONT_BOLD if bold else _FONT_REGULAR
    c.setFont(font, size)
    if max_width is None:
        c.drawString(x, y, text)
        return size * 1.3

    avg_char_w = pdfmetrics.stringWidth("A", font, size) or size * 0.55
    max_chars = max(8, int(max_width / avg_char_w))
    lines = _wrap_text(text, max_chars)
    line_h = size * 1.25
    cy = y
    for line in lines:
        if align == "center":
            tw = pdfmetrics.stringWidth(line, font, size)
            c.drawString(x + (max_width - tw) / 2, cy, line)
        elif align == "right":
            tw = pdfmetrics.stringWidth(line, font, size)
            c.drawString(x + max_width - tw, cy, line)
        else:
            c.drawString(x, cy, line)
        cy -= line_h
    return y - cy


def _draw_bullets(
    c: canvas.Canvas,
    bullets: list[str],
    x,
    y,
    *,
    width: float,
    color: str,
    accent: str,
    size: int = 16,
) -> None:
    font = _FONT_REGULAR
    avg_char_w = pdfmetrics.stringWidth("A", font, size) or size * 0.55
    indent = 0.35 * inch
    max_chars = max(10, int((width - indent) / avg_char_w))
    line_h = size * 1.35
    cy = y
    for item in bullets:
        c.setFillColor(HexColor(accent))
        c.setFont(_FONT_BOLD, size)
        c.drawString(x, cy, "●")
        c.setFillColor(HexColor(color))
        c.setFont(font, size)
        lines = _wrap_text(item, max_chars)
        for j, line in enumerate(lines):
            c.drawString(x + indent, cy, line)
            if j < len(lines) - 1:
                cy -= line_h
        cy -= line_h * 1.1


def _draw_image(c: canvas.Canvas, img_bytes: bytes, x, y, w, h) -> None:
    try:
        img = PILImage.open(io.BytesIO(img_bytes))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        iw, ih = img.size
        ratio = min(w / iw, h / ih)
        draw_w = iw * ratio
        draw_h = ih * ratio
        offset_x = x + (w - draw_w) / 2
        offset_y = y + (h - draw_h) / 2
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        from reportlab.lib.utils import ImageReader

        c.drawImage(
            ImageReader(buf),
            offset_x,
            offset_y,
            draw_w,
            draw_h,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception:
        pass


def _render_title(c: canvas.Canvas, plan: PresentationPlan, spec: SlideSpec) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["background"])
    _draw_filled_rect(c, 0, PAGE_H - 0.25 * inch, PAGE_W, 0.25 * inch, pal["accent"])
    _draw_filled_rect(c, 0, 0, PAGE_W, 0.25 * inch, pal["accent"])

    title = spec.title or plan.title
    _draw_text(
        c,
        title,
        0.9 * inch,
        PAGE_H - 3.6 * inch,
        color=pal["primary"],
        size=42,
        bold=True,
        align="center",
        max_width=PAGE_W - 1.8 * inch,
    )
    sub = spec.subtitle or plan.subtitle
    if sub:
        _draw_text(
            c,
            sub,
            0.9 * inch,
            PAGE_H - 4.6 * inch,
            color=pal["muted"],
            size=20,
            align="center",
            max_width=PAGE_W - 1.8 * inch,
        )


def _render_section(c: canvas.Canvas, plan: PresentationPlan, spec: SlideSpec) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["primary"])
    _draw_text(
        c,
        spec.title,
        0.9 * inch,
        PAGE_H / 2,
        color=pal["background"],
        size=40,
        bold=True,
        align="center",
        max_width=PAGE_W - 1.8 * inch,
    )
    if spec.subtitle:
        _draw_text(
            c,
            spec.subtitle,
            0.9 * inch,
            PAGE_H / 2 - 0.9 * inch,
            color=pal["accent"],
            size=20,
            align="center",
            max_width=PAGE_W - 1.8 * inch,
        )


def _render_content(
    c: canvas.Canvas,
    plan: PresentationPlan,
    spec: SlideSpec,
    image: bytes | None,
) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["background"])
    _draw_filled_rect(c, 0, 0, 0.18 * inch, PAGE_H, pal["accent"])

    _draw_text(
        c,
        spec.title,
        0.7 * inch,
        PAGE_H - 1.0 * inch,
        color=pal["primary"],
        size=28,
        bold=True,
        max_width=PAGE_W - 1.4 * inch,
    )
    _draw_filled_rect(c, 0.7 * inch, PAGE_H - 1.15 * inch, 1.2 * inch, 0.05 * inch, pal["accent"])

    has_image = image is not None
    left_img = has_image and getattr(spec, "image_placement", "right") == "left"
    text_x = 0.7 * inch
    text_y = PAGE_H - 1.6 * inch
    text_w = PAGE_W - 1.4 * inch
    img_x = 7.4 * inch
    img_y = 0.5 * inch
    img_w = PAGE_W - img_x - 0.5 * inch
    img_h = PAGE_H - 2.0 * inch
    if has_image:
        if left_img:
            img_x = 0.65 * inch
            img_w = 6.35 * inch
            img_h = PAGE_H - 2.0 * inch
            text_x = 7.45 * inch
            text_w = PAGE_W - text_x - 0.55 * inch
        else:
            text_w = 6.4 * inch

    if spec.bullets:
        _draw_bullets(
            c,
            spec.bullets,
            text_x,
            text_y,
            width=text_w,
            color=pal["text"],
            accent=pal["accent"],
            size=16,
        )
    elif spec.body:
        _draw_text(
            c,
            spec.body,
            text_x,
            text_y,
            color=pal["text"],
            size=15,
            max_width=text_w,
        )

    if has_image:
        _draw_image(c, image, img_x, img_y, img_w, img_h)


def _render_two_column(
    c: canvas.Canvas,
    plan: PresentationPlan,
    spec: SlideSpec,
    image: bytes | None,
) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["background"])
    _draw_filled_rect(c, 0, 0, 0.18 * inch, PAGE_H, pal["accent"])
    _draw_text(
        c,
        spec.title,
        0.7 * inch,
        PAGE_H - 1.0 * inch,
        color=pal["primary"],
        size=28,
        bold=True,
        max_width=PAGE_W - 1.4 * inch,
    )
    half = (PAGE_W - 2.1 * inch) / 2
    bullets = spec.bullets or []
    left_b = bullets[: max(1, len(bullets) // 2)] or bullets
    right_b = bullets[len(left_b) :]

    _draw_bullets(
        c,
        left_b,
        0.7 * inch,
        PAGE_H - 1.7 * inch,
        width=half,
        color=pal["text"],
        accent=pal["accent"],
    )
    if right_b:
        _draw_bullets(
            c,
            right_b,
            0.7 * inch + half + 0.7 * inch,
            PAGE_H - 1.7 * inch,
            width=half,
            color=pal["text"],
            accent=pal["accent"],
        )
    elif image is not None:
        _draw_image(
            c,
            image,
            0.7 * inch + half + 0.7 * inch,
            0.6 * inch,
            half,
            PAGE_H - 2.4 * inch,
        )


def _render_conclusion(
    c: canvas.Canvas, plan: PresentationPlan, spec: SlideSpec
) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["background"])
    _draw_filled_rect(c, 0, PAGE_H - 0.25 * inch, PAGE_W, 0.25 * inch, pal["accent"])
    _draw_text(
        c,
        spec.title or "Выводы",
        0.9 * inch,
        PAGE_H - 1.4 * inch,
        color=pal["primary"],
        size=34,
        bold=True,
        align="center",
        max_width=PAGE_W - 1.8 * inch,
    )
    if spec.bullets:
        _draw_bullets(
            c,
            spec.bullets,
            1.5 * inch,
            PAGE_H - 2.4 * inch,
            width=PAGE_W - 3.0 * inch,
            color=pal["text"],
            accent=pal["accent"],
            size=18,
        )
    elif spec.body:
        _draw_text(
            c,
            spec.body,
            1.5 * inch,
            PAGE_H - 2.4 * inch,
            color=pal["text"],
            size=18,
            align="center",
            max_width=PAGE_W - 3.0 * inch,
        )
    if spec.subtitle:
        _draw_text(
            c,
            spec.subtitle,
            0.9 * inch,
            0.7 * inch,
            color=pal["muted"],
            size=15,
            align="center",
            max_width=PAGE_W - 1.8 * inch,
        )


def _render_table(c: canvas.Canvas, plan: PresentationPlan, spec: SlideSpec) -> None:
    pal = _pdf_pal(plan, spec)
    _draw_filled_rect(c, 0, 0, PAGE_W, PAGE_H, pal["background"])
    _draw_filled_rect(c, 0, 0, 0.18 * inch, PAGE_H, pal["accent"])
    xl = 0.7 * inch

    _draw_text(
        c,
        spec.title,
        xl,
        PAGE_H - 1.0 * inch,
        color=pal["primary"],
        size=28,
        bold=True,
        max_width=PAGE_W - 1.4 * inch,
    )
    _draw_filled_rect(c, xl, PAGE_H - 1.15 * inch, 1.2 * inch, 0.05 * inch, pal["accent"])
    subtitle_y = PAGE_H - 1.55 * inch
    table_top_gap = 2.2 * inch
    if spec.subtitle:
        _draw_text(
            c,
            spec.subtitle,
            xl,
            subtitle_y,
            color=pal["muted"],
            size=14,
            max_width=PAGE_W - 1.4 * inch,
        )
        table_top_gap = 2.55 * inch

    headers = list(spec.headers or [])
    rows = [list(r) for r in (spec.rows or [])]
    if not headers and rows:
        n = max(len(r) for r in rows)
        headers = [f"Колонка {i + 1}" for i in range(n)]
        rows = [(r + [""] * n)[:n] for r in rows]
    elif headers and rows:
        n = len(headers)
        rows = [(r + [""] * n)[:n] for r in rows]
    else:
        _draw_text(
            c,
            "Нет данных таблицы",
            xl,
            PAGE_H - table_top_gap,
            color=pal["muted"],
            size=14,
            max_width=PAGE_W - 1.4 * inch,
        )
        return

    data = [headers] + rows
    table_w = PAGE_W - 1.4 * inch
    ncols = len(headers)
    col_widths = [table_w / ncols] * ncols
    t = Table(data, colWidths=col_widths, repeatRows=1)
    head_bg = HexColor(pal["accent"])
    head_fg = HexColor("#FFFFFF")
    surf = HexColor(pal.get("surface", "#FFFFFF"))
    txt = HexColor(pal["text"])
    border = HexColor(pal["muted"])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), head_bg),
                ("TEXTCOLOR", (0, 0), (-1, 0), head_fg),
                ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BACKGROUND", (0, 1), (-1, -1), surf),
                ("TEXTCOLOR", (0, 1), (-1, -1), txt),
                ("FONTNAME", (0, 1), (-1, -1), _FONT_REGULAR),
                ("GRID", (0, 0), (-1, -1), 0.5, border),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    avail_h = PAGE_H - table_top_gap - 0.6 * inch
    _w, th = t.wrapOn(c, table_w, avail_h)
    th = min(th, avail_h)
    bottom_y = PAGE_H - table_top_gap - th
    t.drawOn(c, xl, bottom_y)


def build_pdf(
    plan: PresentationPlan,
    images: dict[int, bytes],
    out_path: Path,
) -> Path:
    c = canvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))
    c.setTitle(plan.title)
    for idx, spec in enumerate(plan.slides):
        img = images.get(idx)
        if spec.kind == "title":
            _render_title(c, plan, spec)
        elif spec.kind == "section":
            _render_section(c, plan, spec)
        elif spec.kind == "two_column":
            _render_two_column(c, plan, spec, img)
        elif spec.kind == "conclusion":
            _render_conclusion(c, plan, spec)
        elif spec.kind == "table":
            _render_table(c, plan, spec)
        else:
            _render_content(c, plan, spec, img)
        c.showPage()
    c.save()
    return out_path
