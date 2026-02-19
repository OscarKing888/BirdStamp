from __future__ import annotations

import json
import hashlib
import math
import re
import sys
import threading
from collections import defaultdict
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageColor, ImageDraw
from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QColorDialog,
)

from birdstamp.config import get_config_path
from birdstamp.constants import SUPPORTED_EXTENSIONS
from birdstamp.decoders.image_decoder import decode_image
from birdstamp.discover import discover_inputs
from birdstamp.meta.exiftool import extract_many
from birdstamp.meta.normalize import format_settings_line, normalize_metadata
from birdstamp.meta.pillow_fallback import extract_pillow_metadata
from birdstamp.render.typography import load_font

ALIGN_OPTIONS_VERTICAL = ("top", "center", "bottom")
ALIGN_OPTIONS_HORIZONTAL = ("left", "center", "right")
_FALLBACK_STYLE_OPTIONS = ("normal",)
_FALLBACK_RATIO_OPTIONS: list[tuple[str, float | None]] = [("原比例", None)]
_FALLBACK_MAX_LONG_EDGE_OPTIONS = [0]
_FALLBACK_OUTPUT_FORMAT_OPTIONS: list[tuple[str, str]] = [("jpg", "JPG")]
_FALLBACK_COLOR_PRESETS: list[tuple[str, str]] = [("白色", "#FFFFFF"), ("黑色", "#111111")]
_FALLBACK_DEFAULT_FIELD_TAG = "EXIF:Model"
_FALLBACK_TAG_OPTIONS: list[tuple[str, str]] = [("机身型号 (EXIF)", "EXIF:Model")]
_FALLBACK_SAMPLE_RAW_METADATA: dict[str, Any] = {}
_DEFAULT_FOCUS_BOX_SHORT_EDGE_RATIO = 0.12
_BIRD_MODEL_CANDIDATES = ("yolo11n.pt", "yolo11s.pt", "yolov8n.pt")
_BIRD_CLASS_NAME = "bird"
_COCO_FALLBACK_BIRD_CLASS_ID = 14
_BIRD_DETECT_CONFIDENCE = 0.25
_BIRD_DETECTOR_ERROR_MESSAGE = ""
_CENTER_MODE_IMAGE = "image"
_CENTER_MODE_FOCUS = "focus"
_CENTER_MODE_BIRD = "bird"
_CENTER_MODE_OPTIONS = (_CENTER_MODE_IMAGE, _CENTER_MODE_FOCUS, _CENTER_MODE_BIRD)
_DEFAULT_CROP_EFFECT_ALPHA = 160


@lru_cache(maxsize=1)
def _load_builtin_editor_options_raw() -> dict[str, Any]:
    options_file = resources.files("birdstamp.gui") / "resources" / "editor_options.json"
    text = options_file.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(f"编辑器选项格式错误: {options_file}")
    return raw


def _normalize_style_options(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return _FALLBACK_STYLE_OPTIONS
    items: list[str] = []
    for item in value:
        text = str(item).strip().lower()
        if text and text not in items:
            items.append(text)
    return tuple(items) if items else _FALLBACK_STYLE_OPTIONS


def _normalize_ratio_options(value: Any) -> list[tuple[str, float | None]]:
    if not isinstance(value, list):
        return list(_FALLBACK_RATIO_OPTIONS)
    items: list[tuple[str, float | None]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        ratio_raw = item.get("value")
        ratio: float | None
        if ratio_raw is None:
            ratio = None
        else:
            try:
                ratio = float(ratio_raw)
            except Exception:
                continue
            if ratio <= 0:
                continue
        items.append((label, ratio))
    return items if items else list(_FALLBACK_RATIO_OPTIONS)


def _normalize_max_edges(value: Any) -> list[int]:
    if not isinstance(value, list):
        return list(_FALLBACK_MAX_LONG_EDGE_OPTIONS)
    items: list[int] = []
    for item in value:
        try:
            edge = int(float(item))
        except Exception:
            continue
        if edge < 0:
            continue
        if edge not in items:
            items.append(edge)
    return items if items else list(_FALLBACK_MAX_LONG_EDGE_OPTIONS)


def _normalize_output_formats(value: Any) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return list(_FALLBACK_OUTPUT_FORMAT_OPTIONS)
    items: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        suffix = str(item.get("suffix") or "").strip().lower().lstrip(".")
        label = str(item.get("label") or "").strip()
        if not suffix or not label:
            continue
        items.append((suffix, label))
    return items if items else list(_FALLBACK_OUTPUT_FORMAT_OPTIONS)


def _normalize_labeled_values(value: Any, fallback: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return list(fallback)
    items: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        item_value = str(item.get("value") or "").strip()
        if not label or not item_value:
            continue
        items.append((label, item_value))
    return items if items else list(fallback)


def _normalize_sample_raw_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return dict(_FALLBACK_SAMPLE_RAW_METADATA)
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        text_key = str(key).strip()
        if text_key:
            cleaned[text_key] = item
    return cleaned if cleaned else dict(_FALLBACK_SAMPLE_RAW_METADATA)


def _load_editor_options() -> dict[str, Any]:
    try:
        raw = _load_builtin_editor_options_raw()
    except Exception:
        raw = {}

    style_options = _normalize_style_options(raw.get("style_options"))
    ratio_options = _normalize_ratio_options(raw.get("ratio_options"))
    max_long_edge_options = _normalize_max_edges(raw.get("max_long_edge_options"))
    output_format_options = _normalize_output_formats(raw.get("output_format_options"))
    color_presets = _normalize_labeled_values(raw.get("color_presets"), _FALLBACK_COLOR_PRESETS)
    tag_options = _normalize_labeled_values(raw.get("tag_options"), _FALLBACK_TAG_OPTIONS)
    sample_raw_metadata = _normalize_sample_raw_metadata(raw.get("sample_raw_metadata"))

    default_field_tag = str(raw.get("default_field_tag") or "").strip() or _FALLBACK_DEFAULT_FIELD_TAG

    tag_values = {value for _label, value in tag_options}
    if default_field_tag not in tag_values:
        default_field_tag = tag_options[0][1] if tag_options else _FALLBACK_DEFAULT_FIELD_TAG

    return {
        "style_options": style_options,
        "ratio_options": ratio_options,
        "max_long_edge_options": max_long_edge_options,
        "output_format_options": output_format_options,
        "color_presets": color_presets,
        "default_field_tag": default_field_tag,
        "tag_options": tag_options,
        "sample_raw_metadata": sample_raw_metadata,
    }


_EDITOR_OPTIONS = _load_editor_options()
STYLE_OPTIONS: tuple[str, ...] = _EDITOR_OPTIONS["style_options"]
RATIO_OPTIONS: list[tuple[str, float | None]] = _EDITOR_OPTIONS["ratio_options"]
MAX_LONG_EDGE_OPTIONS: list[int] = _EDITOR_OPTIONS["max_long_edge_options"]
OUTPUT_FORMAT_OPTIONS: list[tuple[str, str]] = _EDITOR_OPTIONS["output_format_options"]
COLOR_PRESETS: list[tuple[str, str]] = _EDITOR_OPTIONS["color_presets"]
DEFAULT_FIELD_TAG: str = _EDITOR_OPTIONS["default_field_tag"]
TAG_OPTIONS: list[tuple[str, str]] = _EDITOR_OPTIONS["tag_options"]
SAMPLE_RAW_METADATA: dict[str, Any] = _EDITOR_OPTIONS["sample_raw_metadata"]


def _safe_color(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    try:
        ImageColor.getrgb(text)
    except ValueError:
        return fallback
    return text


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        for codec in ("utf-8", "utf-16le", "latin1"):
            try:
                value = value.decode(codec, errors="ignore")
                break
            except Exception:
                continue
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value if str(v).strip()]
        value = " ".join(items)
    text = str(value).replace("\x00", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text or None


def _normalize_lookup(raw: dict[str, Any]) -> dict[str, Any]:
    lookup: dict[str, Any] = {}
    for key, value in raw.items():
        key_text = str(key).strip().lower()
        if not key_text:
            continue
        lookup.setdefault(key_text, value)
        if ":" in key_text:
            lookup.setdefault(key_text.split(":")[-1], value)
    return lookup


def _extract_numbers(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, (list, tuple)):
        numbers: list[float] = []
        for item in value:
            numbers.extend(_extract_numbers(item))
        return numbers
    text = str(value)
    tokens = re.findall(r"[-+]?\d+(?:\.\d+)?", text)
    result: list[float] = []
    for token in tokens:
        try:
            result.append(float(token))
        except ValueError:
            continue
    return result


def _is_dimension_like(value: float, size: int) -> bool:
    if size <= 0:
        return False
    if value <= 1.0:
        return False
    size_f = float(size)
    return abs(value - size_f) <= 3.0 or abs(value - (size_f + 1.0)) <= 3.0


def _normalize_focus_coordinate(x: float, y: float, width: int, height: int) -> tuple[float, float]:
    if x > 1.0 or y > 1.0:
        if width > 0 and height > 0:
            return (_clamp01(x / float(width)), _clamp01(y / float(height)))
    return (_clamp01(x), _clamp01(y))


def _decode_focus_numbers_layout(
    numbers: list[float], width: int, height: int
) -> tuple[float, float, float | None, float | None] | None:
    if len(numbers) < 2:
        return None

    # Sony FocusLocation 常见格式: [图宽, 图高, X, Y]
    if len(numbers) >= 4 and _is_dimension_like(numbers[0], width) and _is_dimension_like(numbers[1], height):
        center_x = numbers[2]
        center_y = numbers[3]
        span_start = 4
    else:
        center_x = numbers[0]
        center_y = numbers[1]
        span_start = 2

    span_x: float | None = None
    span_y: float | None = None
    if len(numbers) >= span_start + 2:
        span_x = numbers[span_start]
        span_y = numbers[span_start + 1]
    elif len(numbers) >= span_start + 1:
        span_x = numbers[span_start]
        span_y = numbers[span_start]
    return (center_x, center_y, span_x, span_y)


def _extract_focus_frame_size(value: Any) -> tuple[float, float] | None:
    numbers = _extract_numbers(value)
    if len(numbers) < 2:
        return None
    width = numbers[0]
    height = numbers[1]
    if width <= 0 or height <= 0:
        return None
    return (float(width), float(height))


def _extract_focus_point(raw: dict[str, Any], width: int, height: int) -> tuple[float, float] | None:
    if width <= 0 or height <= 0:
        return None
    lookup = _normalize_lookup(raw)

    key_pairs = [
        ("composite:focusx", "composite:focusy"),
        ("focusx", "focusy"),
        ("regioninfo:regionsregionlistregionareax", "regioninfo:regionsregionlistregionareay"),
        ("regionareax", "regionareay"),
    ]
    for x_key, y_key in key_pairs:
        if x_key in lookup and y_key in lookup:
            xs = _extract_numbers(lookup[x_key])
            ys = _extract_numbers(lookup[y_key])
            if xs and ys:
                x = xs[0]
                y = ys[0]
                if x > 1.0 or y > 1.0:
                    return (max(0.0, min(1.0, x / width)), max(0.0, min(1.0, y / height)))
                return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    for key in ("subjectarea", "subjectlocation", "focuslocation", "focuslocation2", "afpoint"):
        if key not in lookup:
            continue
        nums = _extract_numbers(lookup[key])
        decoded = _decode_focus_numbers_layout(nums, width, height)
        if decoded is None:
            continue
        x, y, _span_x, _span_y = decoded
        return _normalize_focus_coordinate(x, y, width, height)

    return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalize_focus_span(value: float | None, full_size: int, fallback: float) -> float:
    if full_size <= 0:
        return max(0.01, min(1.0, fallback))
    if value is None or value <= 0:
        return max(0.01, min(1.0, fallback))
    span = float(value)
    if span > 1.0:
        span = span / float(full_size)
    return max(0.01, min(1.0, span))


def _focus_box_from_center(center_x: float, center_y: float, span_x: float, span_y: float) -> tuple[float, float, float, float]:
    cx = _clamp01(center_x)
    cy = _clamp01(center_y)
    sx = max(0.01, min(1.0, span_x))
    sy = max(0.01, min(1.0, span_y))
    half_x = sx * 0.5
    half_y = sy * 0.5

    left = cx - half_x
    right = cx + half_x
    top = cy - half_y
    bottom = cy + half_y

    if left < 0.0:
        right = min(1.0, right - left)
        left = 0.0
    if right > 1.0:
        left = max(0.0, left - (right - 1.0))
        right = 1.0
    if top < 0.0:
        bottom = min(1.0, bottom - top)
        top = 0.0
    if bottom > 1.0:
        top = max(0.0, top - (bottom - 1.0))
        bottom = 1.0
    return (left, top, right, bottom)


def _focus_box_from_numbers(
    numbers: list[float],
    width: int,
    height: int,
    fallback_span_px: tuple[float, float] | None = None,
) -> tuple[float, float, float, float] | None:
    if width <= 0 or height <= 0:
        return None

    decoded = _decode_focus_numbers_layout(numbers, width, height)
    if decoded is None:
        return None
    x, y, span_x_raw, span_y_raw = decoded
    center_x, center_y = _normalize_focus_coordinate(x, y, width, height)

    default_side_px = max(24.0, min(width, height) * _DEFAULT_FOCUS_BOX_SHORT_EDGE_RATIO)
    if fallback_span_px is not None and fallback_span_px[0] > 0 and fallback_span_px[1] > 0:
        fallback_span_x = fallback_span_px[0] / float(width)
        fallback_span_y = fallback_span_px[1] / float(height)
    else:
        fallback_span_x = default_side_px / float(width)
        fallback_span_y = default_side_px / float(height)

    span_x = _normalize_focus_span(span_x_raw, width, fallback_span_x)
    span_y = _normalize_focus_span(span_y_raw, height, fallback_span_y)
    return _focus_box_from_center(center_x, center_y, span_x, span_y)


def _extract_focus_box(raw: dict[str, Any], width: int, height: int) -> tuple[float, float, float, float] | None:
    if width <= 0 or height <= 0:
        return None
    lookup = _normalize_lookup(raw)

    focus_frame_span_px: tuple[float, float] | None = None
    for key in ("focusframesize", "focusframesize2"):
        if key not in lookup:
            continue
        parsed = _extract_focus_frame_size(lookup[key])
        if parsed is not None:
            focus_frame_span_px = parsed
            break

    subject_area = lookup.get("subjectarea")
    if subject_area is not None:
        box = _focus_box_from_numbers(_extract_numbers(subject_area), width, height, fallback_span_px=focus_frame_span_px)
        if box is not None:
            return box

    box_key_groups = [
        ("composite:focusx", "composite:focusy", "composite:focusw", "composite:focush"),
        ("focusx", "focusy", "focusw", "focush"),
        (
            "regioninfo:regionsregionlistregionareax",
            "regioninfo:regionsregionlistregionareay",
            "regioninfo:regionsregionlistregionareaw",
            "regioninfo:regionsregionlistregionareah",
        ),
        ("regionareax", "regionareay", "regionareaw", "regionareah"),
    ]

    for x_key, y_key, w_key, h_key in box_key_groups:
        if x_key not in lookup or y_key not in lookup:
            continue
        xs = _extract_numbers(lookup[x_key])
        ys = _extract_numbers(lookup[y_key])
        if not xs or not ys:
            continue
        nums = [xs[0], ys[0]]
        ws = _extract_numbers(lookup.get(w_key))
        hs = _extract_numbers(lookup.get(h_key))
        if ws and hs:
            nums.extend([ws[0], hs[0]])
        box = _focus_box_from_numbers(nums, width, height, fallback_span_px=focus_frame_span_px)
        if box is not None:
            return box

    for key in ("subjectlocation", "focuslocation", "focuslocation2", "afpoint"):
        if key not in lookup:
            continue
        box = _focus_box_from_numbers(_extract_numbers(lookup[key]), width, height, fallback_span_px=focus_frame_span_px)
        if box is not None:
            return box

    focus_point = _extract_focus_point(raw, width, height)
    if focus_point is None:
        return None

    default_side_px = max(24.0, min(width, height) * _DEFAULT_FOCUS_BOX_SHORT_EDGE_RATIO)
    return _focus_box_from_center(
        focus_point[0],
        focus_point[1],
        default_side_px / float(width),
        default_side_px / float(height),
    )


def _transform_focus_box_after_crop(
    focus_box: tuple[float, float, float, float],
    *,
    source_width: int,
    source_height: int,
    ratio: float | None,
    anchor: tuple[float, float],
) -> tuple[float, float, float, float] | None:
    if source_width <= 0 or source_height <= 0:
        return None

    left = focus_box[0] * source_width
    top = focus_box[1] * source_height
    right = focus_box[2] * source_width
    bottom = focus_box[3] * source_height

    width_ref = float(source_width)
    height_ref = float(source_height)

    if ratio is not None and ratio > 0:
        current_ratio = source_width / float(source_height)
        if abs(current_ratio - ratio) >= 0.0001:
            anchor_x = _clamp01(anchor[0])
            anchor_y = _clamp01(anchor[1])
            if current_ratio > ratio:
                new_width = max(1, int(round(source_height * ratio)))
                center_x = int(round(anchor_x * source_width))
                crop_left = max(0, min(source_width - new_width, center_x - (new_width // 2)))
                left -= crop_left
                right -= crop_left
                width_ref = float(new_width)
                height_ref = float(source_height)
            else:
                new_height = max(1, int(round(source_width / ratio)))
                center_y = int(round(anchor_y * source_height))
                crop_top = max(0, min(source_height - new_height, center_y - (new_height // 2)))
                top -= crop_top
                bottom -= crop_top
                width_ref = float(source_width)
                height_ref = float(new_height)

    left_n = left / width_ref
    right_n = right / width_ref
    top_n = top / height_ref
    bottom_n = bottom / height_ref

    if right_n <= 0.0 or left_n >= 1.0 or bottom_n <= 0.0 or top_n >= 1.0:
        return None

    left_n = _clamp01(left_n)
    right_n = _clamp01(right_n)
    top_n = _clamp01(top_n)
    bottom_n = _clamp01(bottom_n)

    if right_n <= left_n or bottom_n <= top_n:
        return None
    return (left_n, top_n, right_n, bottom_n)


def _resize_fit(image: Image.Image, max_long_edge: int) -> Image.Image:
    if max_long_edge <= 0:
        return image
    width, height = image.size
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return image
    scale = max_long_edge / float(long_edge)
    new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _normalize_center_mode(value: Any) -> str:
    text = str(value or _CENTER_MODE_IMAGE).strip().lower()
    if text not in _CENTER_MODE_OPTIONS:
        return _CENTER_MODE_IMAGE
    return text


def _normalize_unit_box(
    box: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    if box is None:
        return None
    try:
        left = _clamp01(float(box[0]))
        top = _clamp01(float(box[1]))
        right = _clamp01(float(box[2]))
        bottom = _clamp01(float(box[3]))
    except Exception:
        return None

    if right < left:
        left, right = right, left
    if bottom < top:
        top, bottom = bottom, top
    if right - left <= 0.0001 or bottom - top <= 0.0001:
        return None
    return (left, top, right, bottom)


def _box_center(box: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5)


def _solve_axis_crop_start(
    *,
    full_size: int,
    crop_size: int,
    anchor_center: float,
    keep_start: float | None = None,
    keep_end: float | None = None,
) -> int:
    if full_size <= 0 or crop_size >= full_size:
        return 0

    max_start = full_size - crop_size
    target_center = _clamp01(anchor_center) * float(full_size)
    start = int(round(target_center - (crop_size * 0.5)))
    start = max(0, min(max_start, start))

    if keep_start is None or keep_end is None:
        return start

    low = min(keep_start, keep_end)
    high = max(keep_start, keep_end)
    feasible_min = max(0, int(math.ceil(high - crop_size)))
    feasible_max = min(max_start, int(math.floor(low)))
    if feasible_min <= feasible_max:
        return max(feasible_min, min(feasible_max, start))

    keep_center = (low + high) * 0.5
    centered = int(round(keep_center - (crop_size * 0.5)))
    return max(0, min(max_start, centered))


def _compute_ratio_crop_box(
    *,
    width: int,
    height: int,
    ratio: float | None,
    anchor: tuple[float, float] = (0.5, 0.5),
    keep_box: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float, float]:
    if width <= 0 or height <= 0 or ratio is None or ratio <= 0:
        return (0.0, 0.0, 1.0, 1.0)

    current = width / float(height)
    if abs(current - ratio) < 0.0001:
        return (0.0, 0.0, 1.0, 1.0)

    keep = _normalize_unit_box(keep_box)
    anchor_x = _clamp01(anchor[0])
    anchor_y = _clamp01(anchor[1])

    if current > ratio:
        crop_w = max(1, min(width, int(round(height * ratio))))
        left = _solve_axis_crop_start(
            full_size=width,
            crop_size=crop_w,
            anchor_center=anchor_x,
            keep_start=(keep[0] * width) if keep else None,
            keep_end=(keep[2] * width) if keep else None,
        )
        right = left + crop_w
        return (
            _clamp01(left / float(width)),
            0.0,
            _clamp01(right / float(width)),
            1.0,
        )

    crop_h = max(1, min(height, int(round(width / ratio))))
    top = _solve_axis_crop_start(
        full_size=height,
        crop_size=crop_h,
        anchor_center=anchor_y,
        keep_start=(keep[1] * height) if keep else None,
        keep_end=(keep[3] * height) if keep else None,
    )
    bottom = top + crop_h
    return (
        0.0,
        _clamp01(top / float(height)),
        1.0,
        _clamp01(bottom / float(height)),
    )


def _crop_box_has_effect(crop_box: tuple[float, float, float, float] | None) -> bool:
    normalized = _normalize_unit_box(crop_box)
    if normalized is None:
        return False
    eps = 0.0005
    return (
        normalized[0] > eps
        or normalized[1] > eps
        or normalized[2] < (1.0 - eps)
        or normalized[3] < (1.0 - eps)
    )


def _crop_image_by_normalized_box(
    image: Image.Image,
    crop_box: tuple[float, float, float, float] | None,
) -> Image.Image:
    normalized = _normalize_unit_box(crop_box)
    if normalized is None:
        return image
    width, height = image.size
    if width <= 0 or height <= 0:
        return image

    left = int(round(normalized[0] * width))
    top = int(round(normalized[1] * height))
    right = int(round(normalized[2] * width))
    bottom = int(round(normalized[3] * height))
    left = max(0, min(width - 1, left))
    top = max(0, min(height - 1, top))
    right = max(left + 1, min(width, right))
    bottom = max(top + 1, min(height, bottom))
    if left <= 0 and top <= 0 and right >= width and bottom >= height:
        return image
    return image.crop((left, top, right, bottom))


def _crop_to_ratio_with_anchor(image: Image.Image, ratio: float, anchor: tuple[float, float]) -> Image.Image:
    crop_box = _compute_ratio_crop_box(
        width=image.width,
        height=image.height,
        ratio=ratio,
        anchor=anchor,
        keep_box=None,
    )
    return _crop_image_by_normalized_box(image, crop_box)


def _pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    q_image = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(q_image.copy())


def _resolve_bird_class_ids(names: Any) -> set[int]:
    ids: set[int] = set()
    if isinstance(names, dict):
        iterator = names.items()
    elif isinstance(names, (list, tuple)):
        iterator = enumerate(names)
    else:
        iterator = []

    for raw_idx, raw_name in iterator:
        if str(raw_name).strip().lower() != _BIRD_CLASS_NAME:
            continue
        try:
            ids.add(int(raw_idx))
        except Exception:
            continue

    if not ids:
        ids.add(_COCO_FALLBACK_BIRD_CLASS_ID)
    return ids


def _short_error_text(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"\s+", " ", text)
    if len(text) > 180:
        return f"{text[:177]}..."
    return text


def _best_bird_box_from_result(result: Any, bird_class_ids: set[int]) -> tuple[float, float, float, float] | None:
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return None

    try:
        xyxy_rows = boxes.xyxy.tolist()
        cls_values = boxes.cls.tolist()
        conf_values = boxes.conf.tolist()
    except Exception:
        return None

    total = min(len(xyxy_rows), len(cls_values), len(conf_values))
    if total <= 0:
        return None

    best_box: tuple[float, float, float, float] | None = None
    best_conf = -1.0
    best_area = -1.0
    for idx in range(total):
        try:
            cls_id = int(round(float(cls_values[idx])))
        except Exception:
            continue
        if cls_id not in bird_class_ids:
            continue

        row = xyxy_rows[idx]
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        try:
            x1 = float(row[0])
            y1 = float(row[1])
            x2 = float(row[2])
            y2 = float(row[3])
            conf = float(conf_values[idx])
        except Exception:
            continue

        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        if conf > best_conf or (abs(conf - best_conf) <= 1e-9 and area > best_area):
            best_conf = conf
            best_area = area
            best_box = (x1, y1, x2, y2)

    return best_box


def _normalize_xyxy_box(
    box: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[float, float, float, float] | None:
    if width <= 0 or height <= 0:
        return None
    left_px = min(box[0], box[2])
    right_px = max(box[0], box[2])
    top_px = min(box[1], box[3])
    bottom_px = max(box[1], box[3])

    left = _clamp01(left_px / float(width))
    right = _clamp01(right_px / float(width))
    top = _clamp01(top_px / float(height))
    bottom = _clamp01(bottom_px / float(height))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


@lru_cache(maxsize=1)
def _load_torch_module() -> Any | None:
    global _BIRD_DETECTOR_ERROR_MESSAGE
    try:
        import torch as torch_module
    except Exception as exc:
        text = _short_error_text(exc)
        if "numpy" in text.lower():
            _BIRD_DETECTOR_ERROR_MESSAGE = "当前 Torch/NumPy 版本不兼容，请安装 numpy<2 或升级匹配版本"
        else:
            _BIRD_DETECTOR_ERROR_MESSAGE = f"加载 torch 失败: {text}"
        return None
    return torch_module


@lru_cache(maxsize=1)
def _load_yolo_class() -> Any | None:
    global _BIRD_DETECTOR_ERROR_MESSAGE
    try:
        from ultralytics import YOLO as yolo_class
    except Exception as exc:
        text = _short_error_text(exc)
        if "numpy" in text.lower():
            _BIRD_DETECTOR_ERROR_MESSAGE = "当前 Torch/NumPy 版本不兼容，请安装 numpy<2 或升级匹配版本"
        else:
            _BIRD_DETECTOR_ERROR_MESSAGE = f"未安装或无法加载 ultralytics: {text}"
        return None
    return yolo_class


def _preferred_bird_detect_device() -> str | int:
    torch_module = _load_torch_module()
    if torch_module is None:
        return "cpu"
    try:
        if torch_module.cuda.is_available():
            return 0
    except Exception:
        pass
    try:
        backends = getattr(torch_module, "backends", None)
        mps = getattr(backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


@lru_cache(maxsize=1)
def _load_bird_detector() -> tuple[Any, set[int]] | None:
    global _BIRD_DETECTOR_ERROR_MESSAGE
    _BIRD_DETECTOR_ERROR_MESSAGE = ""

    yolo_class = _load_yolo_class()
    if yolo_class is None:
        if not _BIRD_DETECTOR_ERROR_MESSAGE:
            _BIRD_DETECTOR_ERROR_MESSAGE = "未安装 ultralytics（pip install ultralytics）"
        return None

    last_error = ""
    for model_name in _BIRD_MODEL_CANDIDATES:
        try:
            model = yolo_class(f"models/{model_name}")
        except Exception as exc:
            last_error = f"{model_name}: {_short_error_text(exc)}"
            continue
        bird_class_ids = _resolve_bird_class_ids(getattr(model, "names", None))
        if not bird_class_ids:
            last_error = f"{model_name}: 未找到 bird 类别"
            continue
        return (model, bird_class_ids)

    _BIRD_DETECTOR_ERROR_MESSAGE = last_error or "鸟体识别模型加载失败"
    return None


def _detect_primary_bird_box(image: Image.Image) -> tuple[float, float, float, float] | None:
    global _BIRD_DETECTOR_ERROR_MESSAGE
    detector = _load_bird_detector()
    if detector is None:
        return None

    _BIRD_DETECTOR_ERROR_MESSAGE = ""
    model, bird_class_ids = detector
    source = image if image.mode == "RGB" else image.convert("RGB")
    detect_device = _preferred_bird_detect_device()
    predict_kwargs = {
        "source": source,
        "conf": _BIRD_DETECT_CONFIDENCE,
        "verbose": False,
    }

    try:
        results = model.predict(device=detect_device, **predict_kwargs)
    except Exception as primary_exc:
        primary_text = _short_error_text(primary_exc)
        if detect_device == "cpu":
            if "Numpy is not available" in primary_text:
                _BIRD_DETECTOR_ERROR_MESSAGE = "当前 Torch/NumPy 版本不兼容，请安装 numpy<2 或升级匹配版本"
            else:
                _BIRD_DETECTOR_ERROR_MESSAGE = f"鸟体识别推理失败: {primary_text}"
            return None
        try:
            results = model.predict(device="cpu", **predict_kwargs)
        except Exception as fallback_exc:
            fallback_text = _short_error_text(fallback_exc)
            if "Numpy is not available" in fallback_text:
                _BIRD_DETECTOR_ERROR_MESSAGE = "当前 Torch/NumPy 版本不兼容，请安装 numpy<2 或升级匹配版本"
            else:
                _BIRD_DETECTOR_ERROR_MESSAGE = f"鸟体识别推理失败: {primary_text}; CPU 回退失败: {fallback_text}"
            return None

    if not results:
        return None
    best_box = _best_bird_box_from_result(results[0], bird_class_ids)
    if best_box is None:
        return None
    return _normalize_xyxy_box(best_box, source.width, source.height)


def _template_directory() -> Path:
    return get_config_path().parent / "templates"


@lru_cache(maxsize=1)
def _load_builtin_default_template_raw() -> dict[str, Any]:
    default_file = resources.files("birdstamp.gui") / "resources" / "default_template.json"
    text = default_file.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(f"默认模板格式错误: {default_file}")
    return raw


def _deep_copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _default_template_field() -> dict[str, Any]:
    raw = _load_builtin_default_template_raw()
    fields = raw.get("fields")
    if isinstance(fields, list):
        for index, item in enumerate(fields):
            if isinstance(item, dict):
                return _normalize_template_field(item, index=index)
    return _normalize_template_field({}, index=0)


def _default_template_payload(name: str = "default") -> dict[str, Any]:
    raw = _deep_copy_payload(_load_builtin_default_template_raw())
    raw["name"] = name or str(raw.get("name") or "default")
    return _normalize_template_payload(raw, fallback_name=str(raw["name"]))


def _clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def _normalize_template_field(data: dict[str, Any], index: int) -> dict[str, Any]:
    align_h = str(data.get("align_horizontal") or data.get("align") or "left").lower()
    if align_h not in ALIGN_OPTIONS_HORIZONTAL:
        align_h = "left"

    align_v = str(data.get("align_vertical") or "top").lower()
    if align_v not in ALIGN_OPTIONS_VERTICAL:
        align_v = "top"

    style = str(data.get("style") or "normal").lower()
    if style not in STYLE_OPTIONS:
        style = STYLE_OPTIONS[0]

    return {
        "name": str(data.get("name") or f"字段{index + 1}"),
        "tag": str(data.get("tag") or DEFAULT_FIELD_TAG),
        "fallback": str(data.get("fallback") or ""),
        "align_horizontal": align_h,
        "align_vertical": align_v,
        "x_offset_pct": round(_clamp_float(data.get("x_offset_pct"), -100.0, 100.0, 0.0), 2),
        "y_offset_pct": round(_clamp_float(data.get("y_offset_pct"), -100.0, 100.0, 5.0), 2),
        "color": _safe_color(str(data.get("color") or "#FFFFFF"), "#FFFFFF"),
        "font_size": _clamp_int(data.get("font_size"), 8, 300, 24),
        "style": style,
    }


def _normalize_template_payload(payload: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    fields_raw = payload.get("fields")
    fields: list[dict[str, Any]] = []
    if isinstance(fields_raw, list):
        for index, item in enumerate(fields_raw):
            if isinstance(item, dict):
                fields.append(_normalize_template_field(item, index=index))

    if not fields:
        fields.append(_default_template_field())

    return {
        "name": str(payload.get("name") or fallback_name),
        "fields": fields,
    }


def _load_template_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError(f"模板格式错误: {path}")
    return _normalize_template_payload(raw, fallback_name=path.stem)


def _save_template_payload(path: Path, payload: dict[str, Any]) -> None:
    normalized = _normalize_template_payload(payload, fallback_name=path.stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_template_repository(template_dir: Path) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    has_json = any(path.suffix.lower() == ".json" for path in template_dir.iterdir() if path.is_file())
    if has_json:
        return
    default_path = template_dir / "default.json"
    _save_template_payload(default_path, _default_template_payload(name="default"))


def _list_template_names(template_dir: Path) -> list[str]:
    names: list[str] = []
    for path in sorted(template_dir.glob("*.json")):
        if path.is_file():
            names.append(path.stem)
    return names


def _format_with_context(text: str, context: dict[str, str]) -> str:
    if not text:
        return ""
    safe = defaultdict(str, context)
    try:
        return text.format_map(safe)
    except Exception:
        return text


def _lookup_tag_value(tag: str, lookup: dict[str, Any], context: dict[str, str]) -> str | None:
    token = (tag or "").strip()
    if not token:
        return None

    lowered = token.lower()
    if lowered in context:
        text = _clean_text(context[lowered])
        if text:
            return text

    value = lookup.get(lowered)
    if value is None and ":" in lowered:
        value = lookup.get(lowered.split(":")[-1])
    if value is None:
        suffix = f":{lowered}"
        for key, candidate in lookup.items():
            if key.endswith(suffix):
                value = candidate
                break

    text = _clean_text(value)
    if text:
        return text
    return None


def _draw_styled_text(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    x: int,
    y: int,
    color: str,
    font,
    style: str,
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width = max(1, right - left)
    height = max(1, bottom - top)

    layer = Image.new("RGBA", (width + 10, height + 10), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)

    text_pos = (5 - left, 5 - top)
    is_bold = style in {"bold", "bold_italic"}
    is_italic = style in {"italic", "bold_italic"}

    if is_bold:
        offsets = [(0, 0), (1, 0), (0, 1)]
        for dx, dy in offsets:
            layer_draw.text((text_pos[0] + dx, text_pos[1] + dy), text, font=font, fill=color)
    else:
        layer_draw.text(text_pos, text, font=font, fill=color)

    if is_italic:
        shear = -0.28
        new_width = int(round(layer.width + abs(shear) * layer.height))
        layer = layer.transform(
            (max(1, new_width), layer.height),
            Image.Transform.AFFINE,
            (1, shear, 0, 0, 1, 0),
            resample=Image.Resampling.BICUBIC,
        )

    image.alpha_composite(layer, (x - 5, y - 5))


def render_template_overlay(
    image: Image.Image,
    *,
    raw_metadata: dict[str, Any],
    metadata_context: dict[str, str],
    template_payload: dict[str, Any],
) -> Image.Image:
    canvas = image.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    lookup = _normalize_lookup(raw_metadata)

    fields = template_payload.get("fields") or []
    if not isinstance(fields, list):
        fields = []

    for field_index, raw_field in enumerate(fields):
        if not isinstance(raw_field, dict):
            continue
        field = _normalize_template_field(raw_field, field_index)
        tag = str(field.get("tag") or "")

        text = _lookup_tag_value(tag, lookup, metadata_context)
        if not text:
            fallback = _format_with_context(str(field.get("fallback") or ""), metadata_context)
            text = _clean_text(fallback)
        if not text:
            continue

        font_size = int(field.get("font_size") or 24)
        font = load_font(None, font_size)
        color = _safe_color(str(field.get("color") or "#FFFFFF"), "#FFFFFF")

        text_box = draw.textbbox((0, 0), text, font=font)
        text_width = max(1, text_box[2] - text_box[0])
        text_height = max(1, text_box[3] - text_box[1])

        align_h = str(field.get("align_horizontal") or field.get("align") or "left").lower()
        align_v = str(field.get("align_vertical") or "top").lower()
        x_offset = float(field.get("x_offset_pct") or 0.0) / 100.0
        y_offset = float(field.get("y_offset_pct") or 0.0) / 100.0

        if align_h == "center":
            anchor_x = int(round((canvas.width * 0.5) + (canvas.width * x_offset)))
            x = anchor_x - (text_width // 2)
        elif align_h == "right":
            anchor_x = int(round(canvas.width + (canvas.width * x_offset)))
            x = anchor_x - text_width
        else:
            anchor_x = int(round(canvas.width * x_offset))
            x = anchor_x

        if align_v == "center":
            anchor_y = int(round((canvas.height * 0.5) + (canvas.height * y_offset)))
            y = anchor_y - (text_height // 2)
        elif align_v == "bottom":
            anchor_y = int(round(canvas.height + (canvas.height * y_offset)))
            y = anchor_y - text_height
        else:
            anchor_y = int(round(canvas.height * y_offset))
            y = anchor_y

        x = max(0, min(canvas.width - text_width, x))
        y = max(0, min(canvas.height - text_height, y))

        _draw_styled_text(
            canvas,
            draw,
            text,
            x=x,
            y=y,
            color=color,
            font=font,
            style=str(field.get("style") or "normal"),
        )

    return canvas.convert("RGB")


def _build_metadata_context(path: Path, raw_metadata: dict[str, Any]) -> dict[str, str]:
    context: dict[str, str] = {
        "bird": "",
        "capture_text": "",
        "location": "",
        "gps_text": "",
        "camera": "",
        "lens": "",
        "settings_text": "",
        "stem": path.stem,
        "filename": path.name,
    }

    try:
        normalized = normalize_metadata(
            path,
            raw_metadata,
            bird_arg=None,
            bird_priority=["meta", "filename"],
            bird_regex=r"(?P<bird>[^_]+)_",
            time_format="%Y-%m-%d %H:%M",
        )
    except Exception:
        return context

    context["bird"] = normalized.bird or ""
    context["capture_text"] = normalized.capture_text or ""
    context["location"] = normalized.location or ""
    context["gps_text"] = normalized.gps_text or ""
    context["camera"] = normalized.camera or ""
    context["lens"] = normalized.lens or ""
    settings = normalized.settings_text or format_settings_line(normalized, show_eq_focal=True) or ""
    context["settings_text"] = settings
    return context


def _build_placeholder_image(width: int = 1600, height: int = 1000) -> Image.Image:
    width = max(320, width)
    height = max(220, height)
    image = Image.new("RGB", (width, height), color="#2C3340")
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / float(max(1, height - 1))
        r = int(40 + (58 - 40) * ratio)
        g = int(49 + (70 - 49) * ratio)
        b = int(62 + (86 - 62) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b), width=1)

    block_h = max(36, height // 12)
    for row in range(0, height, block_h):
        if (row // block_h) % 2 == 0:
            draw.rectangle((0, row, width, min(height, row + block_h // 2)), fill=(57, 68, 83))

    margin_x = width // 8
    margin_y = height // 6
    draw.rectangle(
        (margin_x, margin_y, width - margin_x, height - margin_y),
        outline="#9FB5CC",
        width=max(2, width // 400),
    )

    text = "模板预览占位图\n(后续可替换为你提供的图片)"
    font = load_font(None, max(20, width // 42))
    lines = text.splitlines()
    total_height = 0
    line_sizes: list[tuple[int, int]] = []
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        line_w, line_h = box[2] - box[0], box[3] - box[1]
        line_sizes.append((line_w, line_h))
        total_height += line_h + 8

    y = (height - total_height) // 2
    for idx, line in enumerate(lines):
        line_w, line_h = line_sizes[idx]
        x = (width - line_w) // 2
        draw.text((x, y), line, fill="#E9EEF6", font=font)
        y += line_h + 8

    return image


def _sanitize_template_name(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    safe = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    safe = safe.replace(" ", "_").strip("._")
    return safe


def _path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


class PreviewCanvas(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("暂无预览", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._source_pixmap: QPixmap | None = None
        self._focus_box: tuple[float, float, float, float] | None = None
        self._bird_box: tuple[float, float, float, float] | None = None
        self._crop_effect_box: tuple[float, float, float, float] | None = None
        self._show_focus_box = True
        self._show_bird_box = False
        self._show_crop_effect = False
        self._crop_effect_alpha = _DEFAULT_CROP_EFFECT_ALPHA
        self._use_original_size = False
        self._zoom = 1.0
        self._offset = QPointF(0.0, 0.0)
        self._dragging = False
        self._last_drag_pos = QPointF(0.0, 0.0)
        self._min_zoom = 0.02
        self._max_zoom = 24.0

    def set_focus_box(self, focus_box: tuple[float, float, float, float] | None) -> None:
        self._focus_box = focus_box
        self.update()

    def set_show_focus_box(self, enabled: bool) -> None:
        self._show_focus_box = bool(enabled)
        self.update()

    def set_bird_box(self, bird_box: tuple[float, float, float, float] | None) -> None:
        self._bird_box = bird_box
        self.update()

    def set_show_bird_box(self, enabled: bool) -> None:
        self._show_bird_box = bool(enabled)
        self.update()

    def set_crop_effect_box(self, crop_effect_box: tuple[float, float, float, float] | None) -> None:
        self._crop_effect_box = crop_effect_box
        self.update()

    def set_show_crop_effect(self, enabled: bool) -> None:
        self._show_crop_effect = bool(enabled)
        self.update()

    def set_crop_effect_alpha(self, alpha: int) -> None:
        parsed = max(0, min(255, int(alpha)))
        if parsed == self._crop_effect_alpha:
            return
        self._crop_effect_alpha = parsed
        self.update()

    def _fit_scale(self) -> float:
        if self._source_pixmap is None:
            return 1.0
        if self._use_original_size:
            return 1.0
        content = self.contentsRect()
        if content.width() <= 0 or content.height() <= 0:
            return 1.0
        pix_w = max(1, self._source_pixmap.width())
        pix_h = max(1, self._source_pixmap.height())
        return min(content.width() / float(pix_w), content.height() / float(pix_h))

    def _view_center_ratio(self) -> tuple[float, float] | None:
        draw_rect = self._display_rect()
        if draw_rect is None or draw_rect.width() <= 0 or draw_rect.height() <= 0:
            return None
        canvas_center = QPointF(self.contentsRect().center())
        return (
            (canvas_center.x() - draw_rect.left()) / draw_rect.width(),
            (canvas_center.y() - draw_rect.top()) / draw_rect.height(),
        )

    def _apply_view_center_ratio(self, ratio: tuple[float, float]) -> None:
        if self._source_pixmap is None:
            return
        content = self.contentsRect()
        if content.width() <= 0 or content.height() <= 0:
            return
        fit_scale = self._fit_scale() * self._zoom
        if fit_scale <= 0:
            return
        draw_w = self._source_pixmap.width() * fit_scale
        draw_h = self._source_pixmap.height() * fit_scale
        canvas_center = QPointF(content.center())
        center_x = canvas_center.x() + ((0.5 - ratio[0]) * draw_w)
        center_y = canvas_center.y() + ((0.5 - ratio[1]) * draw_h)
        self._offset = QPointF(center_x - canvas_center.x(), center_y - canvas_center.y())

    def set_use_original_size(
        self,
        enabled: bool,
        *,
        reset_view: bool = False,
        preserve_view: bool = False,
        preserve_scale: bool = False,
    ) -> None:
        target = bool(enabled)
        if self._source_pixmap is None:
            self._use_original_size = target
            if reset_view:
                self._zoom = 1.0
                self._offset = QPointF(0.0, 0.0)
            self._clamp_offset()
            self._update_cursor()
            self.update()
            return

        view_ratio = self._view_center_ratio() if preserve_view else None
        old_total_scale = self._fit_scale() * self._zoom

        if target == self._use_original_size:
            if reset_view:
                self._zoom = 1.0
                self._offset = QPointF(0.0, 0.0)
            elif view_ratio is not None:
                self._apply_view_center_ratio(view_ratio)
                self._clamp_offset()
                self._update_cursor()
                self.update()
            return

        self._use_original_size = target
        if preserve_scale:
            new_fit_scale = self._fit_scale()
            if new_fit_scale > 0:
                self._zoom = max(self._min_zoom, min(self._max_zoom, old_total_scale / new_fit_scale))
        if reset_view:
            self._zoom = 1.0
            self._offset = QPointF(0.0, 0.0)
        elif view_ratio is not None:
            self._apply_view_center_ratio(view_ratio)
        self._clamp_offset()
        self._update_cursor()
        self.update()

    def set_source_pixmap(
        self,
        pixmap: QPixmap | None,
        *,
        reset_view: bool = False,
        preserve_view: bool = False,
        preserve_scale: bool = False,
    ) -> None:
        old_pixmap = self._source_pixmap
        view_ratio = self._view_center_ratio() if preserve_view else None
        old_total_scale = self._fit_scale() * self._zoom

        self._source_pixmap = pixmap
        if self._source_pixmap is None or self._source_pixmap.isNull():
            self._source_pixmap = None
            self._focus_box = None
            self._bird_box = None
            self._crop_effect_box = None
            self._zoom = 1.0
            self._offset = QPointF(0.0, 0.0)
            self._dragging = False
            self.setText("暂无预览")
            self._update_cursor()
            self.update()
            return

        if preserve_scale and old_pixmap is not None and not old_pixmap.isNull():
            try:
                old_w = float(max(1, old_pixmap.width()))
                old_h = float(max(1, old_pixmap.height()))
                new_w = float(max(1, self._source_pixmap.width()))
                new_h = float(max(1, self._source_pixmap.height()))
                # 切换原图/预览图时按分辨率比例换算缩放，保持像素级观察连续。
                ratio_w = old_w / new_w
                ratio_h = old_h / new_h
                if abs(ratio_w - ratio_h) <= 0.03:
                    old_total_scale *= ((ratio_w + ratio_h) * 0.5)
                else:
                    old_total_scale *= ratio_w
            except Exception:
                pass

        if preserve_scale:
            new_fit_scale = self._fit_scale()
            if new_fit_scale > 0:
                self._zoom = max(self._min_zoom, min(self._max_zoom, old_total_scale / new_fit_scale))
        if reset_view:
            self._zoom = 1.0
            self._offset = QPointF(0.0, 0.0)
        elif view_ratio is not None:
            self._apply_view_center_ratio(view_ratio)
        self._clamp_offset()
        self._update_cursor()
        self.setText("")
        self.update()

    def _display_rect(self) -> QRectF | None:
        if self._source_pixmap is None:
            return None
        content = self.contentsRect()
        if content.width() <= 0 or content.height() <= 0:
            return None
        scale = self._fit_scale() * self._zoom
        if scale <= 0:
            return None
        draw_w = self._source_pixmap.width() * scale
        draw_h = self._source_pixmap.height() * scale
        center = QPointF(content.center()) + self._offset
        return QRectF(
            center.x() - (draw_w * 0.5),
            center.y() - (draw_h * 0.5),
            draw_w,
            draw_h,
        )

    def _can_pan(self) -> bool:
        draw_rect = self._display_rect()
        if draw_rect is None:
            return False
        content = self.contentsRect()
        return (draw_rect.width() > content.width() + 0.5) or (draw_rect.height() > content.height() + 0.5)

    def _clamp_offset(self) -> None:
        if self._source_pixmap is None:
            self._offset = QPointF(0.0, 0.0)
            return
        content = self.contentsRect()
        if content.width() <= 0 or content.height() <= 0:
            self._offset = QPointF(0.0, 0.0)
            return

        scale = self._fit_scale() * self._zoom
        draw_w = self._source_pixmap.width() * scale
        draw_h = self._source_pixmap.height() * scale

        limit_x = max(0.0, (draw_w - content.width()) * 0.5)
        limit_y = max(0.0, (draw_h - content.height()) * 0.5)

        clamped_x = max(-limit_x, min(limit_x, self._offset.x()))
        clamped_y = max(-limit_y, min(limit_y, self._offset.y()))
        self._offset = QPointF(clamped_x, clamped_y)

    def _update_cursor(self) -> None:
        if self._source_pixmap is None or not self._can_pan():
            self.unsetCursor()
            return
        if self._dragging:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._clamp_offset()
        self._update_cursor()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if self._source_pixmap is None:
            super().wheelEvent(event)
            return

        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return

        old_zoom = self._zoom
        zoom_factor = pow(1.0015, float(delta))
        new_zoom = max(self._min_zoom, min(self._max_zoom, old_zoom * zoom_factor))
        if abs(new_zoom - old_zoom) < 1e-9:
            event.accept()
            return

        fit_scale = self._fit_scale()
        if fit_scale <= 0:
            event.ignore()
            return

        content = self.contentsRect()
        canvas_center = QPointF(content.center())
        cursor_pos = event.position()

        old_scale = fit_scale * old_zoom
        new_scale = fit_scale * new_zoom
        if old_scale <= 0 or new_scale <= 0:
            event.ignore()
            return

        image_center = canvas_center + self._offset
        image_dx = (cursor_pos.x() - image_center.x()) / old_scale
        image_dy = (cursor_pos.y() - image_center.y()) / old_scale

        new_image_center = QPointF(
            cursor_pos.x() - (image_dx * new_scale),
            cursor_pos.y() - (image_dy * new_scale),
        )

        self._zoom = new_zoom
        self._offset = new_image_center - canvas_center
        self._clamp_offset()
        self._update_cursor()
        self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._source_pixmap is not None
            and self._can_pan()
        ):
            self._dragging = True
            self._last_drag_pos = event.position()
            self._update_cursor()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._dragging:
            delta = event.position() - self._last_drag_pos
            self._last_drag_pos = event.position()
            self._offset += delta
            self._clamp_offset()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._update_cursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._source_pixmap is None:
            return

        draw_rect = self._display_rect()
        if draw_rect is None:
            return

        content = self.contentsRect()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setClipRect(content)
        painter.drawPixmap(
            draw_rect,
            self._source_pixmap,
            QRectF(0, 0, self._source_pixmap.width(), self._source_pixmap.height()),
        )

        if self._show_bird_box and self._bird_box:
            bird_left = draw_rect.left() + (self._bird_box[0] * draw_rect.width())
            bird_top = draw_rect.top() + (self._bird_box[1] * draw_rect.height())
            bird_right = draw_rect.left() + (self._bird_box[2] * draw_rect.width())
            bird_bottom = draw_rect.top() + (self._bird_box[3] * draw_rect.height())
            bird_rect = QRectF(
                min(bird_left, bird_right),
                min(bird_top, bird_bottom),
                abs(bird_right - bird_left),
                abs(bird_bottom - bird_top),
            )
            bird_rect = bird_rect.intersected(QRectF(content))
            if bird_rect.width() >= 1.0 and bird_rect.height() >= 1.0:
                fill_color = QColor("#A9DBFF")
                fill_color.setAlpha(96)
                painter.fillRect(bird_rect, fill_color)

                bird_pen = QPen(QColor("#8BCBFF"))
                bird_pen.setWidth(1)
                bird_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(bird_pen)
                painter.drawRect(bird_rect)

        if self._show_focus_box and self._focus_box:
            left = int(round(draw_rect.left() + (self._focus_box[0] * draw_rect.width())))
            top = int(round(draw_rect.top() + (self._focus_box[1] * draw_rect.height())))
            right = int(round(draw_rect.left() + (self._focus_box[2] * draw_rect.width())))
            bottom = int(round(draw_rect.top() + (self._focus_box[3] * draw_rect.height())))

            content_left = content.left()
            content_top = content.top()
            content_right = content_left + content.width() - 1
            content_bottom = content_top + content.height() - 1

            if content_right - content_left >= 2 and content_bottom - content_top >= 2:
                left = max(content_left, min(content_right - 2, left))
                top = max(content_top, min(content_bottom - 2, top))
                right = min(content_right, max(left + 2, right))
                bottom = min(content_bottom, max(top + 2, bottom))

                box_w = right - left
                box_h = bottom - top

                painter.setBrush(Qt.BrushStyle.NoBrush)

                outer_pen = QPen(QColor("#000000"))
                outer_pen.setWidth(1)
                outer_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                painter.setPen(outer_pen)
                painter.drawRect(left, top, box_w, box_h)

                if box_w >= 4 and box_h >= 4:
                    focus_pen = QPen(QColor("#2EFF55"))
                    focus_pen.setWidth(2)
                    focus_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    painter.setPen(focus_pen)
                    painter.drawRect(left + 1, top + 1, max(1, box_w - 2), max(1, box_h - 2))

                if box_w >= 8 and box_h >= 8:
                    inner_pen = QPen(QColor("#000000"))
                    inner_pen.setWidth(1)
                    inner_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    painter.setPen(inner_pen)
                    painter.drawRect(left + 3, top + 3, box_w - 6, box_h - 6)

        if self._show_crop_effect and self._crop_effect_box:
            crop_left = draw_rect.left() + (self._crop_effect_box[0] * draw_rect.width())
            crop_top = draw_rect.top() + (self._crop_effect_box[1] * draw_rect.height())
            crop_right = draw_rect.left() + (self._crop_effect_box[2] * draw_rect.width())
            crop_bottom = draw_rect.top() + (self._crop_effect_box[3] * draw_rect.height())
            crop_rect = QRectF(
                min(crop_left, crop_right),
                min(crop_top, crop_bottom),
                abs(crop_right - crop_left),
                abs(crop_bottom - crop_top),
            )
            visible_rect = draw_rect.intersected(QRectF(content))
            crop_rect = crop_rect.intersected(visible_rect)
            if visible_rect.width() >= 1.0 and visible_rect.height() >= 1.0 and crop_rect.width() >= 1.0 and crop_rect.height() >= 1.0:
                shade_path = QPainterPath()
                shade_path.addRect(visible_rect)
                keep_path = QPainterPath()
                keep_path.addRect(crop_rect)
                shade_path = shade_path.subtracted(keep_path)
                painter.fillPath(shade_path, QColor(0, 0, 0, self._crop_effect_alpha))

        painter.end()


class PhotoListWidget(QListWidget):
    pathsDropped = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)

    def dragEnterEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[override]
        urls = event.mimeData().urls()
        incoming: list[Path] = []
        for url in urls:
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                incoming.append(path)
            elif path.is_dir():
                incoming.extend(discover_inputs(path, recursive=True))

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in incoming:
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)

        if deduped:
            self.pathsDropped.emit(deduped)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class TemplateManagerDialog(QDialog):
    def __init__(self, template_dir: Path, placeholder: Image.Image | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("模板管理")
        self.resize(1180, 780)
        self.setMinimumSize(1000, 680)

        self.template_dir = template_dir
        self.placeholder = placeholder.copy() if placeholder else _build_placeholder_image()
        self.preview_pixmap: QPixmap | None = None

        self.template_paths: dict[str, Path] = {}
        self.current_template_name: str | None = None
        self.current_payload: dict[str, Any] | None = None
        self._updating = False

        self._setup_ui()
        self._reload_template_list(preferred=None)
        self._refresh_preview_label()

    def _setup_ui(self) -> None:
        root_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("模板列表"))
        self.template_list = QListWidget()
        self.template_list.currentItemChanged.connect(self._on_template_selected)
        left_layout.addWidget(self.template_list, stretch=1)

        left_buttons = QHBoxLayout()
        btn_new = QPushButton("新增")
        btn_new.clicked.connect(self._create_template)
        left_buttons.addWidget(btn_new)

        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(self._copy_template)
        left_buttons.addWidget(btn_copy)

        btn_delete = QPushButton("删除")
        btn_delete.clicked.connect(self._delete_template)
        left_buttons.addWidget(btn_delete)
        left_layout.addLayout(left_buttons)

        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(8, 8, 8, 8)
        editor_layout.setSpacing(8)

        header_group = QGroupBox("当前模板")
        header_form = QFormLayout(header_group)
        self.template_name_edit = QLineEdit()
        self.template_name_edit.setReadOnly(True)
        header_form.addRow("模板文件", self.template_name_edit)
        editor_layout.addWidget(header_group)

        fields_group = QGroupBox("文本项")
        fields_layout = QVBoxLayout(fields_group)
        self.field_list = QListWidget()
        self.field_list.currentItemChanged.connect(self._on_field_selected)
        fields_layout.addWidget(self.field_list)

        field_buttons = QHBoxLayout()
        add_field_btn = QPushButton("新增文本项")
        add_field_btn.clicked.connect(self._add_field)
        field_buttons.addWidget(add_field_btn)

        remove_field_btn = QPushButton("删除文本项")
        remove_field_btn.clicked.connect(self._remove_field)
        field_buttons.addWidget(remove_field_btn)
        fields_layout.addLayout(field_buttons)
        editor_layout.addWidget(fields_group, stretch=1)

        edit_group = QGroupBox("文本项编辑")
        edit_form = QFormLayout(edit_group)

        self.field_name_edit = QLineEdit()
        self.field_name_edit.textChanged.connect(self._apply_field_changes)
        edit_form.addRow("名称", self.field_name_edit)

        self.field_tag_combo = QComboBox()
        for label, value in TAG_OPTIONS:
            self.field_tag_combo.addItem(label, value)
        self.field_tag_combo.currentIndexChanged.connect(self._apply_field_changes)
        edit_form.addRow("Exif标签", self.field_tag_combo)

        self.field_fallback_edit = QLineEdit()
        self.field_fallback_edit.setPlaceholderText("可用 {bird} {capture_text} 等")
        self.field_fallback_edit.textChanged.connect(self._apply_field_changes)
        edit_form.addRow("Fallback", self.field_fallback_edit)

        self.field_align_h_combo = QComboBox()
        self.field_align_h_combo.addItems(list(ALIGN_OPTIONS_HORIZONTAL))
        self.field_align_h_combo.currentTextChanged.connect(self._apply_field_changes)
        edit_form.addRow("水平对齐", self.field_align_h_combo)

        self.field_align_v_combo = QComboBox()
        self.field_align_v_combo.addItems(list(ALIGN_OPTIONS_VERTICAL))
        self.field_align_v_combo.currentTextChanged.connect(self._apply_field_changes)
        edit_form.addRow("垂直对齐", self.field_align_v_combo)

        self.field_x_spin = QDoubleSpinBox()
        self.field_x_spin.setRange(-100.0, 100.0)
        self.field_x_spin.setDecimals(2)
        self.field_x_spin.setSingleStep(0.5)
        self.field_x_spin.valueChanged.connect(self._apply_field_changes)
        edit_form.addRow("X偏移(%)", self.field_x_spin)

        self.field_y_spin = QDoubleSpinBox()
        self.field_y_spin.setRange(-100.0, 100.0)
        self.field_y_spin.setDecimals(2)
        self.field_y_spin.setSingleStep(0.5)
        self.field_y_spin.valueChanged.connect(self._apply_field_changes)
        edit_form.addRow("Y偏移(%)", self.field_y_spin)

        color_row = QWidget()
        color_row_layout = QHBoxLayout(color_row)
        color_row_layout.setContentsMargins(0, 0, 0, 0)
        color_row_layout.setSpacing(6)

        self.field_color_combo = QComboBox()
        for label, value in COLOR_PRESETS:
            self.field_color_combo.addItem(f"{label} {value}", value)
        self.field_color_combo.addItem("自定义", "custom")
        self.field_color_combo.currentIndexChanged.connect(self._on_color_preset_changed)
        color_row_layout.addWidget(self.field_color_combo, stretch=1)

        self.field_color_edit = QLineEdit("#FFFFFF")
        self.field_color_edit.textChanged.connect(self._apply_field_changes)
        color_row_layout.addWidget(self.field_color_edit, stretch=1)

        pick_color_btn = QPushButton("调色板")
        pick_color_btn.clicked.connect(self._pick_field_color)
        color_row_layout.addWidget(pick_color_btn)
        edit_form.addRow("文本颜色", color_row)

        self.field_font_size_spin = QSpinBox()
        self.field_font_size_spin.setRange(8, 300)
        self.field_font_size_spin.valueChanged.connect(self._apply_field_changes)
        edit_form.addRow("字体大小", self.field_font_size_spin)

        self.field_style_combo = QComboBox()
        self.field_style_combo.addItems(list(STYLE_OPTIONS))
        self.field_style_combo.currentTextChanged.connect(self._apply_field_changes)
        edit_form.addRow("字体样式", self.field_style_combo)

        editor_layout.addWidget(edit_group)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        editor_layout.addLayout(close_row)

        preview_panel = QWidget()
        preview_layout_root = QVBoxLayout(preview_panel)
        preview_layout_root.setContentsMargins(8, 8, 8, 8)
        preview_layout_root.setSpacing(8)

        preview_group = QGroupBox("预览")
        preview_layout = QVBoxLayout(preview_group)
        self.preview_label = QLabel("暂无预览")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_label, stretch=1)
        preview_layout_root.addWidget(preview_group, stretch=1)

        splitter.addWidget(left_panel)
        splitter.addWidget(editor_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([260, 520, 400])

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview_label()

    def _reload_template_list(self, preferred: str | None) -> None:
        _ensure_template_repository(self.template_dir)
        names = _list_template_names(self.template_dir)
        self.template_paths = {name: self.template_dir / f"{name}.json" for name in names}

        self.template_list.blockSignals(True)
        self.template_list.clear()
        for name in names:
            self.template_list.addItem(name)
        self.template_list.blockSignals(False)

        if not names:
            self.current_template_name = None
            self.current_payload = None
            self._populate_field_list([])
            self._refresh_preview()
            return

        target = preferred if preferred in self.template_paths else names[0]
        for idx in range(self.template_list.count()):
            item = self.template_list.item(idx)
            if item and item.text() == target:
                self.template_list.setCurrentRow(idx)
                break

    def _on_template_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            return
        name = current.text()
        path = self.template_paths.get(name)
        if not path:
            return
        try:
            payload = _load_template_payload(path)
        except Exception as exc:
            QMessageBox.critical(self, "模板错误", str(exc))
            return

        self.current_template_name = name
        self.current_payload = payload
        self.template_name_edit.setText(path.name)
        self._populate_field_list(payload.get("fields") or [])
        self._refresh_preview()

    def _populate_field_list(self, fields: list[dict[str, Any]]) -> None:
        self.field_list.blockSignals(True)
        self.field_list.clear()
        for idx, field in enumerate(fields):
            display = str(field.get("name") or f"字段{idx + 1}")
            self.field_list.addItem(display)
        self.field_list.blockSignals(False)

        if self.field_list.count() > 0:
            self.field_list.setCurrentRow(0)
        else:
            self._apply_field_to_editor(None)

    def _selected_field_index(self) -> int:
        return self.field_list.currentRow()

    def _selected_field(self) -> dict[str, Any] | None:
        if not self.current_payload:
            return None
        fields = self.current_payload.get("fields") or []
        idx = self._selected_field_index()
        if idx < 0 or idx >= len(fields):
            return None
        field = fields[idx]
        if not isinstance(field, dict):
            return None
        return field

    def _on_field_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            self._apply_field_to_editor(None)
            return
        self._apply_field_to_editor(self._selected_field())

    def _set_tag_combo_value(self, tag: str) -> None:
        target = (tag or DEFAULT_FIELD_TAG).strip()
        idx = self.field_tag_combo.findData(target)
        if idx < 0:
            self.field_tag_combo.addItem(f"保留旧标签: {target}", target)
            idx = self.field_tag_combo.count() - 1
        self.field_tag_combo.setCurrentIndex(idx)

    def _apply_field_to_editor(self, field: dict[str, Any] | None) -> None:
        self._updating = True
        try:
            if not field:
                self.field_name_edit.clear()
                self._set_tag_combo_value(DEFAULT_FIELD_TAG)
                self.field_fallback_edit.clear()
                self.field_align_h_combo.setCurrentText("left")
                self.field_align_v_combo.setCurrentText("top")
                self.field_x_spin.setValue(0.0)
                self.field_y_spin.setValue(0.0)
                self.field_color_edit.setText("#FFFFFF")
                self.field_font_size_spin.setValue(24)
                self.field_style_combo.setCurrentText(STYLE_OPTIONS[0])
                self.field_color_combo.setCurrentIndex(0)
                return

            normalized = _normalize_template_field(field, 0)
            self.field_name_edit.setText(normalized["name"])
            self._set_tag_combo_value(normalized["tag"])
            self.field_fallback_edit.setText(normalized["fallback"])
            self.field_align_h_combo.setCurrentText(normalized["align_horizontal"])
            self.field_align_v_combo.setCurrentText(normalized["align_vertical"])
            self.field_x_spin.setValue(float(normalized["x_offset_pct"]))
            self.field_y_spin.setValue(float(normalized["y_offset_pct"]))
            self.field_color_edit.setText(normalized["color"])
            self.field_font_size_spin.setValue(int(normalized["font_size"]))
            self.field_style_combo.setCurrentText(normalized["style"])

            preset_index = self.field_color_combo.count() - 1
            for idx in range(self.field_color_combo.count() - 1):
                value = str(self.field_color_combo.itemData(idx) or "")
                if value.lower() == normalized["color"].lower():
                    preset_index = idx
                    break
            self.field_color_combo.setCurrentIndex(preset_index)
        finally:
            self._updating = False

    def _on_color_preset_changed(self, *_args: Any) -> None:
        if self._updating:
            return
        value = str(self.field_color_combo.currentData() or "")
        if value and value != "custom":
            self.field_color_edit.setText(value)

    def _pick_field_color(self) -> None:
        initial = QColor(self.field_color_edit.text().strip() or "#ffffff")
        chosen = QColorDialog.getColor(initial, self, "选择文本颜色")
        if not chosen.isValid():
            return
        self.field_color_edit.setText(chosen.name())

    def _apply_field_changes(self, *_args: Any) -> None:
        if self._updating:
            return
        field = self._selected_field()
        if not field or not self.current_payload:
            return

        field["name"] = self.field_name_edit.text().strip() or "字段"
        field["tag"] = str(self.field_tag_combo.currentData() or DEFAULT_FIELD_TAG)
        field["fallback"] = self.field_fallback_edit.text().strip()
        align_h = self.field_align_h_combo.currentText().strip().lower()
        align_v = self.field_align_v_combo.currentText().strip().lower()
        field["align_horizontal"] = align_h if align_h in ALIGN_OPTIONS_HORIZONTAL else "left"
        field["align_vertical"] = align_v if align_v in ALIGN_OPTIONS_VERTICAL else "top"
        field["x_offset_pct"] = round(self.field_x_spin.value(), 2)
        field["y_offset_pct"] = round(self.field_y_spin.value(), 2)
        field["color"] = _safe_color(self.field_color_edit.text(), "#FFFFFF")
        field["font_size"] = int(self.field_font_size_spin.value())
        style = self.field_style_combo.currentText().strip().lower()
        field["style"] = style if style in STYLE_OPTIONS else STYLE_OPTIONS[0]

        idx = self._selected_field_index()
        if idx >= 0:
            item = self.field_list.item(idx)
            if item:
                item.setText(field["name"])

        self._save_current_template()
        self._refresh_preview()

    def _add_field(self) -> None:
        if not self.current_payload:
            return
        fields = self.current_payload.setdefault("fields", [])
        if not isinstance(fields, list):
            fields = []
            self.current_payload["fields"] = fields

        default_field = _normalize_template_field({}, len(fields))
        fields.append(default_field)
        self._populate_field_list(fields)
        self.field_list.setCurrentRow(len(fields) - 1)
        self._save_current_template()
        self._refresh_preview()

    def _remove_field(self) -> None:
        if not self.current_payload:
            return
        fields = self.current_payload.get("fields") or []
        if not isinstance(fields, list) or not fields:
            return

        idx = self._selected_field_index()
        if idx < 0 or idx >= len(fields):
            return

        fields.pop(idx)
        if not fields:
            fields.append(_normalize_template_field({}, 0))
        self.current_payload["fields"] = fields

        self._populate_field_list(fields)
        self.field_list.setCurrentRow(max(0, idx - 1))
        self._save_current_template()
        self._refresh_preview()

    def _create_template(self) -> None:
        name, ok = QInputDialog.getText(self, "新增模板", "模板名(仅文件名):")
        if not ok:
            return
        safe_name = _sanitize_template_name(name)
        if not safe_name:
            QMessageBox.warning(self, "模板管理", "模板名不能为空")
            return

        path = self.template_dir / f"{safe_name}.json"
        if path.exists():
            QMessageBox.warning(self, "模板管理", f"模板已存在: {path.name}")
            return

        payload = _default_template_payload(name=safe_name)
        _save_template_payload(path, payload)
        self._reload_template_list(preferred=safe_name)

    def _copy_template(self) -> None:
        if not self.current_template_name:
            return
        source_path = self.template_paths.get(self.current_template_name)
        if not source_path:
            return

        base_name = f"{self.current_template_name}_copy"
        candidate = base_name
        suffix = 1
        while (self.template_dir / f"{candidate}.json").exists():
            suffix += 1
            candidate = f"{base_name}_{suffix}"

        payload = _load_template_payload(source_path)
        payload["name"] = candidate
        _save_template_payload(self.template_dir / f"{candidate}.json", payload)
        self._reload_template_list(preferred=candidate)

    def _delete_template(self) -> None:
        if not self.current_template_name:
            return
        if len(self.template_paths) <= 1:
            QMessageBox.warning(self, "模板管理", "至少保留一个模板")
            return

        path = self.template_paths.get(self.current_template_name)
        if not path:
            return

        confirm = QMessageBox.question(self, "删除模板", f"确定删除 {path.name} ?")
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "删除失败", str(exc))
            return

        self._reload_template_list(preferred=None)

    def _save_current_template(self) -> None:
        if not self.current_template_name or not self.current_payload:
            return
        path = self.template_paths.get(self.current_template_name)
        if not path:
            return

        payload = _normalize_template_payload(self.current_payload, fallback_name=self.current_template_name)
        payload["name"] = self.current_template_name
        self.current_payload = payload
        _save_template_payload(path, payload)

    def _refresh_preview(self) -> None:
        if not self.current_payload:
            image = self.placeholder.copy()
        else:
            metadata_context = {
                "bird": "灰喜鹊",
                "capture_text": "2026-02-16 09:14",
                "location": "北京海淀",
                "gps_text": "39.12345, 116.12345",
                "camera": "Sony ILCE-1M2",
                "lens": "FE 600mm F4 GM OSS",
                "settings_text": "f/4  1/2000s  ISO800  600mm",
                "stem": "sample",
                "filename": "sample.jpg",
            }
            image = render_template_overlay(
                self.placeholder.copy(),
                raw_metadata=SAMPLE_RAW_METADATA,
                metadata_context=metadata_context,
                template_payload=self.current_payload,
            )

        self.preview_pixmap = _pil_to_qpixmap(image)
        self._refresh_preview_label()

    def _refresh_preview_label(self) -> None:
        if not self.preview_pixmap:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("暂无预览")
            return

        target = self.preview_label.size()
        scaled = self.preview_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setText("")


class BirdStampEditorWindow(QMainWindow):
    def __init__(self, startup_file: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BirdStamp")
        self.resize(1420, 920)
        self.setMinimumSize(1120, 720)

        self.template_dir = _template_directory()
        _ensure_template_repository(self.template_dir)

        self.template_paths: dict[str, Path] = {}
        self.current_template_payload: dict[str, Any] = _default_template_payload(name="default")

        self.preview_pixmap: QPixmap | None = None
        self.preview_focus_box: tuple[float, float, float, float] | None = None
        self.preview_focus_box_original: tuple[float, float, float, float] | None = None
        self.preview_bird_box: tuple[float, float, float, float] | None = None
        self.preview_crop_effect_box: tuple[float, float, float, float] | None = None
        self._original_mode_pixmap: QPixmap | None = None
        self._original_mode_signature: str | None = None
        self._bird_box_cache: dict[str, tuple[float, float, float, float] | None] = {}
        self.photo_render_overrides: dict[str, dict[str, Any]] = {}
        self._bird_detect_error_reported = False
        self._bird_detector_preload_started = False
        self._bird_detector_preload_thread: threading.Thread | None = None
        self.last_rendered: Image.Image | None = None
        self.current_path: Path | None = None
        self.current_source_image: Image.Image | None = None
        self.current_raw_metadata: dict[str, Any] = {}
        self.current_metadata_context: dict[str, str] = {}
        self.raw_metadata_cache: dict[str, dict[str, Any]] = {}

        self.placeholder = _build_placeholder_image(1400, 900)

        self._setup_ui()
        self._setup_shortcuts()
        self._apply_system_adaptive_style()
        self._reload_template_combo(preferred="default")
        self._set_status("就绪。请添加照片并选择模板。")
        self._show_placeholder_preview()
        self._start_bird_detector_preload()

        if startup_file:
            self._add_photo_paths([startup_file])

    def _setup_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        photos_group = QGroupBox("照片列表")
        photos_layout = QVBoxLayout(photos_group)
        photos_layout.setSpacing(6)

        photo_btn_row = QHBoxLayout()
        add_files_btn = QPushButton("添加照片")
        add_files_btn.clicked.connect(self._pick_files)
        photo_btn_row.addWidget(add_files_btn)

        add_dir_btn = QPushButton("添加目录")
        add_dir_btn.clicked.connect(self._pick_directory)
        photo_btn_row.addWidget(add_dir_btn)

        remove_btn = QPushButton("删除所选")
        remove_btn.clicked.connect(self._remove_selected_photos)
        photo_btn_row.addWidget(remove_btn)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._clear_photos)
        photo_btn_row.addWidget(clear_btn)
        photos_layout.addLayout(photo_btn_row)

        self.photo_list = PhotoListWidget()
        self.photo_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.photo_list.pathsDropped.connect(self._add_photo_paths)
        self.photo_list.currentItemChanged.connect(self._on_photo_selected)
        photos_layout.addWidget(self.photo_list, stretch=1)

        hint = QLabel("支持拖入单张照片或整个目录")
        hint.setStyleSheet("color: #7A7A7A;")
        photos_layout.addWidget(hint)

        left_layout.addWidget(photos_group, stretch=2)

        template_group = QGroupBox("模板")
        template_layout = QHBoxLayout(template_group)

        self.template_combo = QComboBox()
        self.template_combo.currentTextChanged.connect(self._on_template_changed)
        template_layout.addWidget(self.template_combo, stretch=1)

        manage_template_btn = QPushButton("模板管理")
        manage_template_btn.clicked.connect(self._open_template_manager)
        template_layout.addWidget(manage_template_btn)
        left_layout.addWidget(template_group)

        output_group = QGroupBox("输出设置")
        output_form = QFormLayout(output_group)

        self.output_format_combo = QComboBox()
        for suffix, label in OUTPUT_FORMAT_OPTIONS:
            self.output_format_combo.addItem(label, suffix)
        if self.output_format_combo.count() == 0:
            self.output_format_combo.addItem("JPG", "jpg")
        output_form.addRow("输出格式", self.output_format_combo)

        self.max_edge_combo = QComboBox()
        seen_edges: set[int] = set()
        for value in MAX_LONG_EDGE_OPTIONS:
            try:
                edge = int(value)
            except Exception:
                continue
            if edge in seen_edges:
                continue
            seen_edges.add(edge)
            if edge <= 0:
                self.max_edge_combo.addItem("不限制", 0)
            else:
                self.max_edge_combo.addItem(str(edge), edge)
        if self.max_edge_combo.count() == 0:
            self.max_edge_combo.addItem("不限制", 0)

        default_max_edge_idx = self.max_edge_combo.findData(1920)
        if default_max_edge_idx >= 0:
            self.max_edge_combo.setCurrentIndex(default_max_edge_idx)
        elif self.max_edge_combo.count() > 1:
            self.max_edge_combo.setCurrentIndex(1)
        else:
            self.max_edge_combo.setCurrentIndex(0)
        self.max_edge_combo.currentIndexChanged.connect(self.render_preview)
        output_form.addRow("最大长边", self.max_edge_combo)

        self.ratio_combo = QComboBox()
        for label, ratio in RATIO_OPTIONS:
            self.ratio_combo.addItem(label, ratio)
        self.ratio_combo.currentIndexChanged.connect(self.render_preview)
        output_form.addRow("裁切比例", self.ratio_combo)

        self.center_mode_combo = QComboBox()
        self.center_mode_combo.addItem("中心", _CENTER_MODE_IMAGE)
        self.center_mode_combo.addItem("焦点", _CENTER_MODE_FOCUS)
        self.center_mode_combo.addItem("鸟体", _CENTER_MODE_BIRD)
        self.center_mode_combo.currentIndexChanged.connect(self.render_preview)
        output_form.addRow("裁切中心", self.center_mode_combo)

        apply_row = QHBoxLayout()
        self.apply_selected_btn = QPushButton("应用")
        self.apply_selected_btn.clicked.connect(self._apply_current_settings_to_selected_photos)
        apply_row.addWidget(self.apply_selected_btn)

        self.apply_all_btn = QPushButton("全部应用")
        self.apply_all_btn.clicked.connect(self._apply_current_settings_to_all_photos)
        apply_row.addWidget(self.apply_all_btn)
        output_form.addRow("裁切重载", apply_row)

        left_layout.addWidget(output_group)

        actions_group = QGroupBox("操作")
        actions_layout = QHBoxLayout(actions_group)
        preview_btn = QPushButton("预览")
        preview_btn.clicked.connect(self.render_preview)
        actions_layout.addWidget(preview_btn)

        export_current_btn = QPushButton("导出当前")
        export_current_btn.clicked.connect(self.export_current)
        actions_layout.addWidget(export_current_btn)

        export_batch_btn = QPushButton("批量导出")
        export_batch_btn.clicked.connect(self.export_all)
        actions_layout.addWidget(export_batch_btn)
        left_layout.addWidget(actions_group)

        left_layout.addStretch(1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.current_file_label = QLabel("当前照片: 未选择")
        right_layout.addWidget(self.current_file_label)

        preview_toolbar = QHBoxLayout()
        preview_toolbar.setContentsMargins(0, 0, 0, 0)
        preview_toolbar.setSpacing(8)

        self.show_original_size_check = QCheckBox("显示原尺寸图")
        self.show_original_size_check.toggled.connect(self._on_preview_scale_mode_toggled)
        preview_toolbar.addWidget(self.show_original_size_check)

        self.show_crop_effect_check = QCheckBox("显示裁切效果")
        self.show_crop_effect_check.setChecked(False)
        self.show_crop_effect_check.toggled.connect(self._on_preview_toolbar_toggled)
        preview_toolbar.addWidget(self.show_crop_effect_check)

        self.crop_effect_alpha_label = QLabel("Alpha")
        preview_toolbar.addWidget(self.crop_effect_alpha_label)

        self.crop_effect_alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self.crop_effect_alpha_slider.setRange(0, 255)
        self.crop_effect_alpha_slider.setSingleStep(1)
        self.crop_effect_alpha_slider.setPageStep(16)
        self.crop_effect_alpha_slider.setValue(_DEFAULT_CROP_EFFECT_ALPHA)
        self.crop_effect_alpha_slider.setFixedWidth(120)
        self.crop_effect_alpha_slider.valueChanged.connect(self._on_crop_effect_alpha_changed)
        preview_toolbar.addWidget(self.crop_effect_alpha_slider)

        self.crop_effect_alpha_value_label = QLabel(str(_DEFAULT_CROP_EFFECT_ALPHA))
        self.crop_effect_alpha_value_label.setMinimumWidth(28)
        preview_toolbar.addWidget(self.crop_effect_alpha_value_label)

        self.show_focus_box_check = QCheckBox("显示对焦点")
        self.show_focus_box_check.setChecked(True)
        self.show_focus_box_check.toggled.connect(self._on_preview_toolbar_toggled)
        preview_toolbar.addWidget(self.show_focus_box_check)

        self.show_bird_box_check = QCheckBox("显示鸟体框")
        self.show_bird_box_check.setChecked(False)
        self.show_bird_box_check.toggled.connect(self._on_preview_toolbar_toggled)
        preview_toolbar.addWidget(self.show_bird_box_check)
        preview_toolbar.addStretch(1)
        right_layout.addLayout(preview_toolbar)

        self.preview_label = PreviewCanvas()
        self.preview_label.setObjectName("PreviewLabel")
        right_layout.addWidget(self.preview_label, stretch=1)

        self.preview_info_label = QLabel("原始分辨率: - | 当前预览分辨率: -")
        self.preview_info_label.setObjectName("PreviewInfoLabel")
        right_layout.addWidget(self.preview_info_label)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([500, 920])

        self.setStatusBar(self.statusBar())

    def _setup_shortcuts(self) -> None:
        action_add = QAction(self)
        action_add.setShortcut(QKeySequence.StandardKey.Open)
        action_add.triggered.connect(self._pick_files)
        self.addAction(action_add)

        action_preview = QAction(self)
        action_preview.setShortcut(QKeySequence("Ctrl+R"))
        action_preview.triggered.connect(self.render_preview)
        self.addAction(action_preview)

        action_export_current = QAction(self)
        action_export_current.setShortcut(QKeySequence("Ctrl+E"))
        action_export_current.triggered.connect(self.export_current)
        self.addAction(action_export_current)

        action_export_all = QAction(self)
        action_export_all.setShortcut(QKeySequence("Ctrl+Shift+E"))
        action_export_all.triggered.connect(self.export_all)
        self.addAction(action_export_all)

    def _apply_system_adaptive_style(self) -> None:
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        base_color = palette.color(QPalette.ColorRole.Base)
        text_color = palette.color(QPalette.ColorRole.Text)
        button_color = palette.color(QPalette.ColorRole.Button)
        button_text = palette.color(QPalette.ColorRole.ButtonText)
        disabled_text = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

        dark_mode = window_color.lightness() < 128
        border_color = window_color.lighter(132) if dark_mode else window_color.darker(130)
        hover_color = button_color.lighter(115) if dark_mode else button_color.darker(105)
        preview_bg = window_color.lighter(108) if dark_mode else window_color.darker(103)

        self.setStyleSheet(
            f"""
            QWidget {{
                font-size: 13px;
            }}
            QGroupBox {{
                border: 1px solid {border_color.name()};
                border-radius: 10px;
                margin-top: 10px;
                background: {base_color.name()};
            }}
            QGroupBox::title {{
                left: 10px;
                padding: 0 4px;
                font-weight: 600;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget {{
                border: 1px solid {border_color.name()};
                border-radius: 7px;
                padding: 4px 6px;
                background: {base_color.name()};
                color: {text_color.name()};
            }}
            QPushButton {{
                border: 1px solid {border_color.name()};
                border-radius: 7px;
                background: {button_color.name()};
                color: {button_text.name()};
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background: {hover_color.name()};
            }}
            QPushButton:disabled {{
                color: {disabled_text.name()};
            }}
            QLabel#PreviewLabel {{
                border: 1px solid {border_color.name()};
                border-radius: 10px;
                background: {preview_bg.name()};
                color: {text_color.name()};
            }}
            QLabel#PreviewInfoLabel {{
                color: {text_color.name()};
                padding: 2px 4px;
            }}
            """
        )

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview_label()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange}:
            self._apply_system_adaptive_style()
        super().changeEvent(event)

    def _on_preview_toolbar_toggled(self, _checked: bool) -> None:
        if self.show_bird_box_check.isChecked():
            self.preview_bird_box = self._current_bird_box()
        else:
            self.preview_bird_box = None
        if self.show_crop_effect_check.isChecked():
            self.preview_crop_effect_box = self._current_crop_effect_box()
        else:
            self.preview_crop_effect_box = None
        self._refresh_preview_label(preserve_view=True)

    def _on_preview_scale_mode_toggled(self, _checked: bool) -> None:
        self._refresh_preview_label(preserve_view=True)

    def _on_crop_effect_alpha_changed(self, value: int) -> None:
        alpha = max(0, min(255, int(value)))
        self.crop_effect_alpha_value_label.setText(str(alpha))
        self.preview_label.set_crop_effect_alpha(alpha)

    def _start_bird_detector_preload(self) -> None:
        if self._bird_detector_preload_started:
            return
        self._bird_detector_preload_started = True

        def _worker() -> None:
            _load_bird_detector()

        thread = threading.Thread(
            target=_worker,
            name="birdstamp-bird-detector-preload",
            daemon=True,
        )
        self._bird_detector_preload_thread = thread
        thread.start()

    def _source_signature(self, path: Path) -> str:
        try:
            stat = path.stat()
            return f"{_path_key(path)}:{stat.st_size}:{stat.st_mtime_ns}"
        except Exception:
            return _path_key(path)

    def _preview_cache_file_for_source(self, path: Path, signature: str) -> Path:
        digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:12]
        preview_dir = path.parent / ".preview"
        return preview_dir / f"{path.stem}.{digest}.png"

    def _invalidate_original_mode_cache(self) -> None:
        self._original_mode_signature = None
        self._original_mode_pixmap = None

    def _load_original_mode_pixmap(self) -> QPixmap | None:
        if self.current_path is None or self.current_source_image is None:
            return None

        signature = self._source_signature(self.current_path)
        if (
            self._original_mode_signature == signature
            and self._original_mode_pixmap is not None
            and not self._original_mode_pixmap.isNull()
        ):
            return self._original_mode_pixmap

        # 优先直接使用原图像内存绘制，避免额外中间文件。
        try:
            direct_pixmap = _pil_to_qpixmap(self.current_source_image)
            if not direct_pixmap.isNull():
                self._original_mode_signature = signature
                self._original_mode_pixmap = direct_pixmap
                return direct_pixmap
        except Exception:
            pass

        cache_path = self._preview_cache_file_for_source(self.current_path, signature)
        if cache_path.exists():
            cached = QPixmap(str(cache_path))
            if not cached.isNull():
                self._original_mode_signature = signature
                self._original_mode_pixmap = cached
                return cached

        # 直接绘制不可用时，落盘到原图目录下 .preview 并复用。
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if not cache_path.exists():
                self.current_source_image.save(cache_path, format="PNG", optimize=True)
            cached = QPixmap(str(cache_path))
            if not cached.isNull():
                self._original_mode_signature = signature
                self._original_mode_pixmap = cached
                return cached
        except Exception:
            return None
        return None

    def _current_focus_box_after_processing(self, *, apply_ratio_crop: bool = True) -> tuple[float, float, float, float] | None:
        if self.current_source_image is None:
            return None

        source_width, source_height = self.current_source_image.size
        focus_box = _extract_focus_box(self.current_raw_metadata, source_width, source_height)
        if focus_box is None:
            return None
        if not apply_ratio_crop:
            return focus_box

        ratio = self._selected_ratio()
        center_mode = self._selected_center_mode()
        anchor = (0.5, 0.5)
        if center_mode == _CENTER_MODE_FOCUS:
            focus_point = _extract_focus_point(self.current_raw_metadata, source_width, source_height)
            if focus_point is not None:
                anchor = focus_point
            else:
                bird_box = self._current_bird_box()
                if bird_box is not None:
                    anchor = _box_center(bird_box)
        elif center_mode == _CENTER_MODE_BIRD:
            bird_box = self._current_bird_box()
            if bird_box is not None:
                anchor = _box_center(bird_box)
            else:
                focus_point = _extract_focus_point(self.current_raw_metadata, source_width, source_height)
                if focus_point is not None:
                    anchor = focus_point

        return _transform_focus_box_after_crop(
            focus_box,
            source_width=source_width,
            source_height=source_height,
            ratio=ratio,
            anchor=anchor,
        )

    def _current_bird_box(self) -> tuple[float, float, float, float] | None:
        if self.current_path is None or self.current_source_image is None:
            return None
        return self._bird_box_for_path(self.current_path, source_image=self.current_source_image)

    def _show_placeholder_preview(self) -> None:
        self.preview_pixmap = _pil_to_qpixmap(self.placeholder)
        self.preview_focus_box = None
        self.preview_focus_box_original = None
        self.preview_bird_box = None
        self.preview_crop_effect_box = None
        self._invalidate_original_mode_cache()
        self._refresh_preview_label(reset_view=True)

    def _update_preview_info_label(self, display_pixmap: QPixmap | None, source_mode: str) -> None:
        if self.current_source_image is None:
            original_text = "-"
            current_text = "-"
        else:
            orig_w, orig_h = self.current_source_image.size
            original_text = f"{orig_w}x{orig_h}"
            if display_pixmap is not None and not display_pixmap.isNull():
                current_text = f"{display_pixmap.width()}x{display_pixmap.height()}"
            else:
                current_text = "-"

        self.preview_info_label.setText(
            f"原始分辨率: {original_text} | 当前预览分辨率: {current_text} ({source_mode})"
        )

    def _refresh_preview_label(self, *, reset_view: bool = False, preserve_view: bool = False) -> None:
        self.preview_label.set_use_original_size(
            self.show_original_size_check.isChecked(),
            reset_view=False,
            preserve_view=preserve_view,
            preserve_scale=preserve_view,
        )
        self.preview_label.set_crop_effect_alpha(self.crop_effect_alpha_slider.value())
        self.preview_label.set_show_crop_effect(self.show_crop_effect_check.isChecked())
        self.preview_label.set_show_focus_box(self.show_focus_box_check.isChecked())
        self.preview_label.set_show_bird_box(self.show_bird_box_check.isChecked())

        display_pixmap: QPixmap | None = self.preview_pixmap
        crop_effect_box = self.preview_crop_effect_box if self.preview_pixmap else None
        focus_box = self.preview_focus_box if self.preview_pixmap else None
        bird_box = self.preview_bird_box if self.preview_pixmap else None
        source_mode = "预览图"

        if self.show_original_size_check.isChecked():
            original_pixmap = self._load_original_mode_pixmap()
            if original_pixmap is not None and not original_pixmap.isNull():
                display_pixmap = original_pixmap
                focus_box = self.preview_focus_box_original
                source_mode = "原图"

        self.preview_label.set_crop_effect_box(crop_effect_box)
        self.preview_label.set_focus_box(focus_box)
        self.preview_label.set_bird_box(bird_box)
        self.preview_label.set_source_pixmap(
            display_pixmap,
            reset_view=reset_view,
            preserve_view=preserve_view,
            preserve_scale=preserve_view,
        )
        self._update_preview_info_label(display_pixmap, source_mode)

    def _reload_template_combo(self, preferred: str | None) -> None:
        _ensure_template_repository(self.template_dir)
        names = _list_template_names(self.template_dir)
        self.template_paths = {name: self.template_dir / f"{name}.json" for name in names}

        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        self.template_combo.addItems(names)
        self.template_combo.blockSignals(False)

        if not names:
            self.current_template_payload = _default_template_payload(name="default")
            return

        selected = preferred if preferred in self.template_paths else names[0]
        self.template_combo.setCurrentText(selected)
        self._load_selected_template(selected)

    def _load_selected_template(self, name: str) -> None:
        path = self.template_paths.get(name)
        if not path:
            return
        try:
            self.current_template_payload = _load_template_payload(path)
        except Exception as exc:
            self._show_error("模板错误", str(exc))
            self.current_template_payload = _default_template_payload(name="default")

    def _on_template_changed(self, name: str) -> None:
        if not name:
            return
        self._load_selected_template(name)
        if self.current_path:
            self.render_preview()

    def _open_template_manager(self) -> None:
        dialog = TemplateManagerDialog(template_dir=self.template_dir, placeholder=self.placeholder, parent=self)
        dialog.exec()
        preferred = dialog.current_template_name
        self._reload_template_combo(preferred=preferred)
        if self.current_path:
            settings = self._render_settings_for_path(self.current_path, prefer_current_ui=False)
            self._apply_render_settings_to_ui(settings)
            self.render_preview()

    def _pick_files(self) -> None:
        ext_pattern = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        file_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "添加照片",
            "",
            f"Images ({ext_pattern});;All Files (*.*)",
        )
        if not file_paths:
            return
        self._add_photo_paths([Path(item) for item in file_paths])

    def _pick_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择目录", "")
        if not folder:
            return
        found = discover_inputs(Path(folder), recursive=True)
        if not found:
            QMessageBox.information(self, "添加目录", "目录中没有支持的图片文件")
            return
        self._add_photo_paths(found)

    def _list_photo_paths(self) -> list[Path]:
        paths: list[Path] = []
        for idx in range(self.photo_list.count()):
            item = self.photo_list.item(idx)
            if not item:
                continue
            raw = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(raw, str):
                paths.append(Path(raw))
        return paths

    def _add_photo_paths(self, paths: Iterable[Path]) -> None:
        existing_keys = {_path_key(path) for path in self._list_photo_paths()}
        default_settings = self._build_current_render_settings()
        add_count = 0

        for incoming in paths:
            path = incoming.resolve(strict=False)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            key = _path_key(path)
            if key in existing_keys:
                continue
            existing_keys.add(key)

            item = QListWidgetItem(path.name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self.photo_list.addItem(item)
            self.photo_render_overrides[key] = self._clone_render_settings(default_settings)
            add_count += 1

        if add_count == 0:
            self._set_status("没有新增照片。")
            return

        if self.photo_list.currentRow() < 0:
            self.photo_list.setCurrentRow(0)

        self._set_status(f"已添加 {add_count} 张照片。")

    def _remove_selected_photos(self) -> None:
        selected_items = self.photo_list.selectedItems()
        if not selected_items:
            return

        removed_keys: list[str] = []
        for item in selected_items:
            raw = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(raw, str):
                removed_keys.append(_path_key(Path(raw)))
            row = self.photo_list.row(item)
            self.photo_list.takeItem(row)

        for key in removed_keys:
            self.raw_metadata_cache.pop(key, None)
            self.photo_render_overrides.pop(key, None)
        if removed_keys:
            self._bird_box_cache.clear()

        if self.photo_list.count() == 0:
            self.current_path = None
            self.current_source_image = None
            self.current_raw_metadata = {}
            self.current_metadata_context = {}
            self.current_file_label.setText("当前照片: 未选择")
            self.last_rendered = None
            self._show_placeholder_preview()

        self._set_status(f"已删除 {len(selected_items)} 项。")

    def _clear_photos(self) -> None:
        self.photo_list.clear()
        self.raw_metadata_cache.clear()
        self.photo_render_overrides.clear()
        self._bird_box_cache.clear()
        self.current_path = None
        self.current_source_image = None
        self.current_raw_metadata = {}
        self.current_metadata_context = {}
        self.current_file_label.setText("当前照片: 未选择")
        self.last_rendered = None
        self._show_placeholder_preview()
        self._set_status("已清空照片列表。")

    def _on_photo_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if not current:
            return
        raw = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(raw, str):
            return
        path = Path(raw)
        if not path.exists():
            self._show_error("文件不存在", str(path))
            return

        try:
            image = decode_image(path, decoder="auto")
        except Exception as exc:
            self._show_error("读取失败", str(exc))
            return

        self.current_path = path
        self.current_source_image = image
        self._invalidate_original_mode_cache()
        self.current_raw_metadata = self._load_raw_metadata(path)
        self.current_metadata_context = _build_metadata_context(path, self.current_raw_metadata)
        settings = self._render_settings_for_path(path, prefer_current_ui=False)
        self._apply_render_settings_to_ui(settings)
        self.current_file_label.setText(f"当前照片: {path}")
        self.render_preview()

    def _load_raw_metadata(self, path: Path) -> dict[str, Any]:
        key = _path_key(path)
        if key in self.raw_metadata_cache:
            return self.raw_metadata_cache[key]

        resolved = path.resolve(strict=False)
        raw_metadata: dict[str, Any]
        try:
            raw_map = extract_many([resolved], mode="auto")
            raw_metadata = raw_map.get(resolved) or extract_pillow_metadata(path)
        except Exception:
            raw_metadata = extract_pillow_metadata(path)
        if not isinstance(raw_metadata, dict):
            raw_metadata = {"SourceFile": str(path)}

        self.raw_metadata_cache[key] = raw_metadata
        return raw_metadata

    def _selected_center_mode(self) -> str:
        return _normalize_center_mode(self.center_mode_combo.currentData())

    def _build_current_render_settings(self) -> dict[str, Any]:
        template_name = str(self.template_combo.currentText() or "default").strip() or "default"
        template_payload = _normalize_template_payload(self.current_template_payload, fallback_name=template_name)
        return {
            "template_name": template_name,
            "template_payload": _deep_copy_payload(template_payload),
            "ratio": self._selected_ratio(),
            "center_mode": self._selected_center_mode(),
            "max_long_edge": self._selected_max_long_edge(),
        }

    def _clone_render_settings(self, settings: dict[str, Any]) -> dict[str, Any]:
        template_name = str(settings.get("template_name") or "default").strip() or "default"
        template_payload_raw = settings.get("template_payload")
        if isinstance(template_payload_raw, dict):
            template_payload = _normalize_template_payload(template_payload_raw, fallback_name=template_name)
        else:
            template_payload = _default_template_payload(name=template_name)

        ratio: float | None
        ratio_raw = settings.get("ratio")
        if ratio_raw is None:
            ratio = None
        else:
            try:
                ratio = float(ratio_raw)
            except Exception:
                ratio = None
            if ratio is not None and ratio <= 0:
                ratio = None

        max_long_edge = 0
        try:
            max_long_edge = int(settings.get("max_long_edge", 0))
        except Exception:
            max_long_edge = 0
        max_long_edge = max(0, max_long_edge)

        return {
            "template_name": template_name,
            "template_payload": _deep_copy_payload(template_payload),
            "ratio": ratio,
            "center_mode": _normalize_center_mode(settings.get("center_mode")),
            "max_long_edge": max_long_edge,
        }

    def _normalize_render_settings(self, raw: Any, fallback: dict[str, Any]) -> dict[str, Any]:
        settings = self._clone_render_settings(fallback)
        if not isinstance(raw, dict):
            return settings

        template_name = str(raw.get("template_name") or settings["template_name"]).strip() or settings["template_name"]
        settings["template_name"] = template_name
        payload_raw = raw.get("template_payload")
        if isinstance(payload_raw, dict):
            settings["template_payload"] = _normalize_template_payload(payload_raw, fallback_name=template_name)

        ratio_raw = raw.get("ratio")
        if ratio_raw is None or ratio_raw == "":
            settings["ratio"] = None
        else:
            try:
                ratio = float(ratio_raw)
            except Exception:
                ratio = settings["ratio"]
            else:
                settings["ratio"] = ratio if ratio > 0 else None

        if "center_mode" in raw:
            settings["center_mode"] = _normalize_center_mode(raw.get("center_mode"))

        if "max_long_edge" in raw:
            try:
                parsed_max_edge = int(raw.get("max_long_edge"))
            except Exception:
                parsed_max_edge = int(settings["max_long_edge"])
            settings["max_long_edge"] = max(0, parsed_max_edge)
        return settings

    def _render_settings_for_path(self, path: Path | None, *, prefer_current_ui: bool) -> dict[str, Any]:
        fallback = self._build_current_render_settings()
        if path is None:
            return fallback
        key = _path_key(path)
        if prefer_current_ui and self.current_path is not None and key == _path_key(self.current_path):
            return fallback
        return self._normalize_render_settings(self.photo_render_overrides.get(key), fallback=fallback)

    def _ratio_combo_index_for_value(self, ratio: float | None) -> int:
        for idx in range(self.ratio_combo.count()):
            data = self.ratio_combo.itemData(idx)
            if data is None and ratio is None:
                return idx
            if data is None or ratio is None:
                continue
            try:
                if abs(float(data) - float(ratio)) <= 0.0001:
                    return idx
            except Exception:
                continue
        return -1

    def _ensure_max_edge_option(self, max_edge: int) -> int:
        edge = max(0, int(max_edge))
        idx = self.max_edge_combo.findData(edge)
        if idx >= 0:
            return idx
        label = "不限制" if edge == 0 else str(edge)
        self.max_edge_combo.addItem(label, edge)
        return self.max_edge_combo.findData(edge)

    def _apply_render_settings_to_ui(self, settings: dict[str, Any]) -> None:
        normalized = self._clone_render_settings(settings)
        template_name = str(normalized["template_name"])

        self.template_combo.blockSignals(True)
        self.ratio_combo.blockSignals(True)
        self.center_mode_combo.blockSignals(True)
        self.max_edge_combo.blockSignals(True)
        try:
            template_idx = self.template_combo.findText(template_name)
            if template_idx >= 0:
                self.template_combo.setCurrentIndex(template_idx)

            ratio_idx = self._ratio_combo_index_for_value(normalized["ratio"])
            if ratio_idx >= 0:
                self.ratio_combo.setCurrentIndex(ratio_idx)

            center_idx = self.center_mode_combo.findData(normalized["center_mode"])
            if center_idx >= 0:
                self.center_mode_combo.setCurrentIndex(center_idx)

            max_edge_idx = self._ensure_max_edge_option(int(normalized["max_long_edge"]))
            if max_edge_idx >= 0:
                self.max_edge_combo.setCurrentIndex(max_edge_idx)
        finally:
            self.max_edge_combo.blockSignals(False)
            self.center_mode_combo.blockSignals(False)
            self.ratio_combo.blockSignals(False)
            self.template_combo.blockSignals(False)

        self.current_template_payload = _normalize_template_payload(
            normalized["template_payload"],
            fallback_name=template_name,
        )

    def _selected_photo_paths(self) -> list[Path]:
        selected_items = self.photo_list.selectedItems()
        paths: list[Path] = []
        if selected_items:
            for item in selected_items:
                raw = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(raw, str):
                    paths.append(Path(raw))
        elif self.current_path is not None:
            paths.append(self.current_path)

        ordered: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        return ordered

    def _apply_current_settings_to_selected_photos(self) -> None:
        targets = self._selected_photo_paths()
        if not targets:
            self._set_status("请先选择要应用设置的照片。")
            return

        snapshot = self._build_current_render_settings()
        for path in targets:
            self.photo_render_overrides[_path_key(path)] = self._clone_render_settings(snapshot)

        if self.current_path is not None:
            current_key = _path_key(self.current_path)
            if any(_path_key(path) == current_key for path in targets):
                self.render_preview()

        self._set_status(f"已将当前裁切重载设置应用到 {len(targets)} 张照片。")

    def _apply_current_settings_to_all_photos(self) -> None:
        targets = self._list_photo_paths()
        if not targets:
            self._set_status("照片列表为空。")
            return

        snapshot = self._build_current_render_settings()
        for path in targets:
            self.photo_render_overrides[_path_key(path)] = self._clone_render_settings(snapshot)

        if self.current_path is not None:
            self.render_preview()
        self._set_status(f"已将当前裁切重载设置应用到全部 {len(targets)} 张照片。")

    def _bird_box_for_path(self, path: Path, *, source_image: Image.Image | None = None) -> tuple[float, float, float, float] | None:
        signature = self._source_signature(path)
        if signature in self._bird_box_cache:
            return self._bird_box_cache[signature]

        image = source_image
        if image is None:
            try:
                image = decode_image(path, decoder="auto")
            except Exception:
                self._bird_box_cache[signature] = None
                return None

        bird_box = _detect_primary_bird_box(image)
        self._bird_box_cache[signature] = bird_box
        if bird_box is None and not self._bird_detect_error_reported and _BIRD_DETECTOR_ERROR_MESSAGE:
            self._set_status(f"鸟体识别不可用: {_BIRD_DETECTOR_ERROR_MESSAGE}")
            self._bird_detect_error_reported = True
        return bird_box

    def _resolve_crop_anchor_and_keep_box(
        self,
        *,
        path: Path | None,
        image: Image.Image,
        raw_metadata: dict[str, Any],
        center_mode: str,
    ) -> tuple[tuple[float, float], tuple[float, float, float, float] | None]:
        focus_point = _extract_focus_point(raw_metadata, image.width, image.height)
        bird_box: tuple[float, float, float, float] | None = None
        if path is not None:
            bird_box = self._bird_box_for_path(path, source_image=image)

        mode = _normalize_center_mode(center_mode)
        anchor = (0.5, 0.5)
        if mode == _CENTER_MODE_FOCUS:
            if focus_point is not None:
                anchor = focus_point
            elif bird_box is not None:
                anchor = _box_center(bird_box)
        elif mode == _CENTER_MODE_BIRD:
            if bird_box is not None:
                anchor = _box_center(bird_box)
            elif focus_point is not None:
                anchor = focus_point
        return (anchor, bird_box)

    def _compute_crop_box_for_image(
        self,
        *,
        path: Path | None,
        image: Image.Image,
        raw_metadata: dict[str, Any],
        settings: dict[str, Any],
    ) -> tuple[float, float, float, float] | None:
        ratio_raw = settings.get("ratio")
        ratio: float | None
        if ratio_raw is None:
            ratio = None
        else:
            try:
                ratio = float(ratio_raw)
            except Exception:
                ratio = None
        if ratio is None or ratio <= 0:
            return None

        anchor, keep_box = self._resolve_crop_anchor_and_keep_box(
            path=path,
            image=image,
            raw_metadata=raw_metadata,
            center_mode=str(settings.get("center_mode") or _CENTER_MODE_IMAGE),
        )
        crop_box = _compute_ratio_crop_box(
            width=image.width,
            height=image.height,
            ratio=ratio,
            anchor=anchor,
            keep_box=keep_box,
        )
        if not _crop_box_has_effect(crop_box):
            return None
        return crop_box

    def _current_crop_effect_box(self) -> tuple[float, float, float, float] | None:
        if self.current_path is None or self.current_source_image is None:
            return None
        settings = self._render_settings_for_path(self.current_path, prefer_current_ui=True)
        return self._compute_crop_box_for_image(
            path=self.current_path,
            image=self.current_source_image,
            raw_metadata=self.current_raw_metadata,
            settings=settings,
        )

    def _selected_ratio(self) -> float | None:
        value = self.ratio_combo.currentData()
        if value is None:
            return None
        try:
            return float(value)
        except Exception:
            return None

    def _selected_max_long_edge(self) -> int:
        value = self.max_edge_combo.currentData()
        try:
            return int(value)
        except Exception:
            return 0

    def _selected_output_suffix(self) -> str:
        value = str(self.output_format_combo.currentData() or "jpg").strip().lower()
        supported = [suffix for suffix, _label in OUTPUT_FORMAT_OPTIONS if suffix in {"jpg", "jpeg", "png"}]
        if not supported:
            supported = ["jpg", "png"]
        if value in supported:
            return value
        return supported[0]

    def _build_processed_image(
        self,
        image: Image.Image,
        raw_metadata: dict[str, Any],
        *,
        settings: dict[str, Any],
        source_path: Path | None,
        apply_ratio_crop: bool = True,
    ) -> Image.Image:
        if apply_ratio_crop:
            crop_box = self._compute_crop_box_for_image(
                path=source_path,
                image=image,
                raw_metadata=raw_metadata,
                settings=settings,
            )
            image = _crop_image_by_normalized_box(image, crop_box)

        max_long_edge = max(0, int(settings.get("max_long_edge") or 0))
        image = _resize_fit(image, max_long_edge)
        return image

    def _render_for_path(self, path: Path, *, prefer_current_ui: bool) -> Image.Image:
        settings = self._render_settings_for_path(path, prefer_current_ui=prefer_current_ui)
        if self.current_path and path == self.current_path and self.current_source_image is not None:
            source_image = self.current_source_image.copy()
            raw_metadata = dict(self.current_raw_metadata)
            context = dict(self.current_metadata_context)
        else:
            source_image = decode_image(path, decoder="auto")
            raw_metadata = self._load_raw_metadata(path)
            context = _build_metadata_context(path, raw_metadata)

        processed = self._build_processed_image(
            source_image,
            raw_metadata,
            settings=settings,
            source_path=path,
            apply_ratio_crop=True,
        )
        rendered = render_template_overlay(
            processed,
            raw_metadata=raw_metadata,
            metadata_context=context,
            template_payload=settings["template_payload"],
        )
        return rendered

    def render_preview(self, *_args: Any) -> None:
        if not self.current_path:
            self._show_placeholder_preview()
            self._set_status("请选择照片后再预览。")
            return

        try:
            if self.current_source_image is None:
                raise RuntimeError("缺少当前原图数据")
            settings = self._render_settings_for_path(self.current_path, prefer_current_ui=True)
            source_image = self.current_source_image.copy()
            raw_metadata = dict(self.current_raw_metadata)
            context = dict(self.current_metadata_context)
            # 预览图始终保持原图长宽比，仅进行尺寸缩放。
            processed = self._build_processed_image(
                source_image,
                raw_metadata,
                settings=settings,
                source_path=self.current_path,
                apply_ratio_crop=False,
            )
            rendered = render_template_overlay(
                processed,
                raw_metadata=raw_metadata,
                metadata_context=context,
                template_payload=settings["template_payload"],
            )
        except Exception as exc:
            self.preview_focus_box = None
            self.preview_focus_box_original = None
            self.preview_bird_box = None
            self.preview_crop_effect_box = None
            self._show_error("预览失败", str(exc))
            self._set_status(f"预览失败: {exc}")
            return

        self.last_rendered = rendered
        self.preview_focus_box = self._current_focus_box_after_processing(apply_ratio_crop=False)
        if self.current_source_image is not None:
            source_width, source_height = self.current_source_image.size
            self.preview_focus_box_original = _extract_focus_box(self.current_raw_metadata, source_width, source_height)
        else:
            self.preview_focus_box_original = None
        if self.show_bird_box_check.isChecked():
            self.preview_bird_box = self._current_bird_box()
        else:
            self.preview_bird_box = None
        if self.show_crop_effect_check.isChecked():
            self.preview_crop_effect_box = self._current_crop_effect_box()
        else:
            self.preview_crop_effect_box = None
        self.preview_pixmap = _pil_to_qpixmap(rendered)
        self._refresh_preview_label(reset_view=True)
        self._set_status(f"预览完成: {rendered.width}x{rendered.height}")

    def export_current(self) -> None:
        if not self.current_path:
            self._set_status("没有可导出的照片。")
            return

        try:
            rendered = self._render_for_path(self.current_path, prefer_current_ui=True)
        except Exception as exc:
            self._show_error("导出失败", str(exc))
            return

        suffix = self._selected_output_suffix()
        default_name = f"{self.current_path.stem}__birdstamp.{suffix}"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前照片",
            default_name,
            "JPG (*.jpg);;PNG (*.png);;All Files (*.*)",
        )
        if not file_path:
            return

        target = Path(file_path)
        if target.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            target = target.with_suffix(f".{suffix}")

        try:
            self._save_image(rendered, target)
        except Exception as exc:
            self._show_error("导出失败", str(exc))
            return

        self._set_status(f"导出完成: {target}")

    def export_all(self) -> None:
        paths = self._list_photo_paths()
        if not paths:
            self._set_status("照片列表为空。")
            return

        output_dir = QFileDialog.getExistingDirectory(self, "选择批量导出目录", "")
        if not output_dir:
            return

        suffix = self._selected_output_suffix()
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        stem_counter: dict[str, int] = {}
        ok_count = 0
        failed: list[str] = []

        for path in paths:
            try:
                rendered = self._render_for_path(path, prefer_current_ui=False)
                stem = f"{path.stem}__birdstamp"
                count = stem_counter.get(stem, 0)
                stem_counter[stem] = count + 1
                if count > 0:
                    file_name = f"{stem}_{count + 1}.{suffix}"
                else:
                    file_name = f"{stem}.{suffix}"
                target = out_dir / file_name
                self._save_image(rendered, target)
                ok_count += 1
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")

        if failed:
            preview = "\n".join(failed[:8])
            if len(failed) > 8:
                preview += f"\n... 另有 {len(failed) - 8} 项失败"
            QMessageBox.warning(self, "批量导出", f"成功 {ok_count}，失败 {len(failed)}\n\n{preview}")
        self._set_status(f"批量导出完成: 成功 {ok_count}，失败 {len(failed)}")

    def _save_image(self, image: Image.Image, path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix == ".png":
            image.save(path, format="PNG", optimize=True)
            return

        if suffix not in {".jpg", ".jpeg"}:
            path = path.with_suffix(".jpg")
        image.save(path, format="JPEG", quality=92, optimize=True, progressive=True)


def launch_gui(startup_file: Path | None = None) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = BirdStampEditorWindow(startup_file=startup_file)
    window.show()
    app.exec()
