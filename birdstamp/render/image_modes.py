from __future__ import annotations

from PIL import Image


def _resize_fit(image: Image.Image, max_long_edge: int) -> Image.Image:
    if max_long_edge <= 0:
        return image
    width, height = image.size
    current_long_edge = max(width, height)
    if current_long_edge <= max_long_edge:
        return image
    scale = max_long_edge / float(current_long_edge)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _crop_to_ratio(image: Image.Image, target_ratio: float) -> Image.Image:
    width, height = image.size
    if height == 0:
        return image
    ratio = width / float(height)
    if abs(ratio - target_ratio) < 0.0001:
        return image

    if ratio > target_ratio:
        new_width = int(height * target_ratio)
        left = (width - new_width) // 2
        box = (left, 0, left + new_width, height)
    else:
        new_height = int(width / target_ratio)
        top = (height - new_height) // 2
        box = (0, top, width, top + new_height)
    return image.crop(box)


def _pad_to_ratio(image: Image.Image, target_ratio: float, fill_color: str) -> Image.Image:
    width, height = image.size
    if height == 0:
        return image
    ratio = width / float(height)
    if abs(ratio - target_ratio) < 0.0001:
        return image

    if ratio > target_ratio:
        new_height = int(round(width / target_ratio))
        canvas = Image.new("RGB", (width, max(height, new_height)), color=fill_color)
        top = (canvas.height - height) // 2
        canvas.paste(image, (0, top))
        return canvas

    new_width = int(round(height * target_ratio))
    canvas = Image.new("RGB", (max(width, new_width), height), color=fill_color)
    left = (canvas.width - width) // 2
    canvas.paste(image, (left, 0))
    return canvas


def _apply_ratio_mode(image: Image.Image, ratio: float, frame_style: str, fill_color: str) -> Image.Image:
    if frame_style == "pad":
        return _pad_to_ratio(image, ratio, fill_color=fill_color)
    return _crop_to_ratio(image, ratio)


def apply_output_mode(
    image: Image.Image,
    mode: str,
    *,
    max_long_edge: int,
    frame_style: str = "crop",
    fill_color: str = "#FFFFFF",
) -> Image.Image:
    mode = mode.lower()
    frame_style = frame_style.lower()

    if mode == "keep":
        return image
    if mode == "fit":
        return _resize_fit(image, max_long_edge=max_long_edge)
    if mode == "square":
        square = _apply_ratio_mode(image, ratio=1.0, frame_style=frame_style, fill_color=fill_color)
        return _resize_fit(square, max_long_edge=max_long_edge)
    if mode == "vertical":
        vertical = _apply_ratio_mode(image, ratio=4.0 / 5.0, frame_style=frame_style, fill_color=fill_color)
        return _resize_fit(vertical, max_long_edge=max_long_edge)
    raise ValueError(f"unsupported output mode: {mode}")

