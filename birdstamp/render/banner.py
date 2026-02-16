from __future__ import annotations

from PIL import Image, ImageDraw

from birdstamp.meta.normalize import format_settings_line
from birdstamp.models import NormalizedMetadata, RenderOptions, RenderTemplate
from birdstamp.render.typography import ellipsize, load_font, text_height, wrap_text


def _rows_height(draw: ImageDraw.ImageDraw, rows: list[tuple[str, object, str]], line_gap: int) -> int:
    if not rows:
        return 0
    total = 0
    for index, (_, font, _) in enumerate(rows):
        total += text_height(draw, font)  # type: ignore[arg-type]
        if index < len(rows) - 1:
            total += line_gap
    return total


def _draw_rows(
    draw: ImageDraw.ImageDraw,
    *,
    rows: list[tuple[str, object, str]],
    x: int,
    y: int,
    width: int,
    line_gap: int,
) -> None:
    current_y = y
    for text, font, color in rows:
        line = ellipsize(draw, text, font, max_width=width)  # type: ignore[arg-type]
        draw.text((x, current_y), line, font=font, fill=color)  # type: ignore[arg-type]
        current_y += text_height(draw, font) + line_gap  # type: ignore[arg-type]


def render_banner(
    image: Image.Image,
    metadata: NormalizedMetadata,
    template: RenderTemplate,
    options: RenderOptions,
) -> Image.Image:
    width, height = image.size
    banner_height = template.banner_height
    output = Image.new("RGB", (width, height + banner_height), color=template.colors["background"])
    output.paste(image, (0, 0))

    draw = ImageDraw.Draw(output)
    banner_top = height
    draw.rectangle(
        [(0, banner_top), (width, height + banner_height)],
        fill=template.colors["background"],
    )

    title_font = load_font(options.font_path, template.fonts["title"])
    body_font = load_font(options.font_path, template.fonts["body"])
    small_font = load_font(options.font_path, template.fonts["small"])

    pad_x = template.padding_x
    pad_y = template.padding_y
    column_gap = max(16, pad_x // 2)

    content_left = pad_x
    content_right = max(content_left + 40, width - pad_x)
    content_width = max(40, content_right - content_left)
    left_width_raw = int(content_width * template.left_ratio)
    left_width = max(30, left_width_raw - (column_gap // 2))
    right_width = max(30, content_width - left_width - column_gap)

    left_x = content_left
    right_x = content_right - right_width
    divider_x = left_x + left_width + (column_gap // 2)

    line_gap = max(4, template.fonts["body"] // 6)

    if template.divider:
        draw.line(
            [(divider_x, banner_top + pad_y), (divider_x, banner_top + banner_height - pad_y)],
            fill=template.colors["divider"],
            width=max(1, width // 1200),
        )

    show = options.show_fields

    left_rows: list[tuple[str, object, str]] = []
    if "bird" in show:
        title = metadata.bird or options.fallback_text
        title_lines = wrap_text(draw, title, title_font, max_width=left_width, max_lines=1)
        if title_lines:
            left_rows.append((title_lines[0], title_font, template.colors["text"]))

    if "time" in show and metadata.capture_text:
        left_rows.append((metadata.capture_text, body_font, template.colors["muted"]))

    location_text = None
    if "location" in show and metadata.location:
        location_text = metadata.location
    elif "gps" in show and metadata.gps_text:
        location_text = metadata.gps_text
    if location_text:
        left_rows.append((location_text, body_font, template.colors["muted"]))

    right_rows: list[tuple[str, object, str]] = []
    if "camera" in show and metadata.camera:
        right_rows.append((metadata.camera, body_font, template.colors["text"]))
    if "lens" in show and metadata.lens:
        right_rows.append((metadata.lens, body_font, template.colors["text"]))
    if "settings" in show:
        settings_line = format_settings_line(metadata, show_eq_focal=options.show_eq_focal)
        if settings_line:
            right_rows.append((settings_line, body_font, template.colors["text"]))

    left_rows = left_rows[:3]
    right_rows = right_rows[:3]

    logo_reserved_height = text_height(draw, small_font) + line_gap if template.logo else 0
    left_available_height = max(30, banner_height - (pad_y * 2) - logo_reserved_height)
    right_available_height = max(30, banner_height - (pad_y * 2))

    left_content_height = _rows_height(draw, left_rows, line_gap=line_gap)
    right_content_height = _rows_height(draw, right_rows, line_gap=line_gap)

    left_start_y = banner_top + pad_y + max(0, (left_available_height - left_content_height) // 2)
    right_start_y = banner_top + pad_y + max(0, (right_available_height - right_content_height) // 2)

    _draw_rows(draw, rows=left_rows, x=left_x, y=left_start_y, width=left_width, line_gap=line_gap)
    _draw_rows(draw, rows=right_rows, x=right_x, y=right_start_y, width=right_width, line_gap=line_gap)

    if template.logo:
        logo_y = banner_top + banner_height - pad_y - text_height(draw, small_font)
        logo_text = ellipsize(draw, template.logo, small_font, left_width)
        draw.text((left_x, logo_y), logo_text, font=small_font, fill=template.colors["muted"])

    return output
