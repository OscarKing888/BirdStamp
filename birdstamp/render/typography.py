from __future__ import annotations

import platform
from pathlib import Path

from PIL import ImageDraw, ImageFont


def _system_font_candidates() -> list[Path]:
    system = platform.system().lower()
    if "windows" in system:
        return [
            Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path(r"C:\Windows\Fonts\simhei.ttf"),
            Path(r"C:\Windows\Fonts\simsun.ttc"),
            Path(r"C:\Windows\Fonts\arial.ttf"),
        ]
    if "darwin" in system:
        return [
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/Library/Fonts/Arial Unicode.ttf"),
        ]
    return [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]


def load_font(font_path: Path | None, size: int) -> ImageFont.ImageFont:
    candidates: list[Path] = []
    if font_path:
        candidates.append(font_path)
    candidates.extend(_system_font_candidates())
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def text_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont) -> int:
    _, height = text_size(draw, "Ag", font)
    return max(1, height)


def ellipsize(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if max_width <= 0:
        return ""
    width, _ = text_size(draw, text, font)
    if width <= max_width:
        return text
    ellipsis = "..."
    for cut in range(len(text), -1, -1):
        candidate = text[:cut].rstrip() + ellipsis
        cand_width, _ = text_size(draw, candidate, font)
        if cand_width <= max_width:
            return candidate
    return ellipsis


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 1,
) -> list[str]:
    clean = (text or "").strip()
    if not clean:
        return []
    if max_lines <= 1:
        return [ellipsize(draw, clean, font, max_width)]

    lines: list[str] = []
    current = ""
    overflow = False
    chars = list(clean)
    idx = 0
    while idx < len(chars):
        ch = chars[idx]
        idx += 1
        if ch == "\n":
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                overflow = idx < len(chars)
                break
            continue
        candidate = current + ch
        width, _ = text_size(draw, candidate, font)
        if width <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current.rstrip())
            current = ch
        else:
            lines.append(ch)
            current = ""
        if len(lines) >= max_lines:
            overflow = idx < len(chars) or bool(current.strip())
            break

    if len(lines) < max_lines and current.strip():
        lines.append(current.rstrip())
    if not lines:
        return []

    if overflow or len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize(draw, lines[-1], font, max_width)
    return lines

