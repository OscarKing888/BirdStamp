# Editor options loaded from editor_options.json (no Qt).
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Any

_FALLBACK_STYLE_OPTIONS = ("normal",)
_FALLBACK_RATIO_OPTIONS: list[tuple[str, float | None]] = [("原比例", None)]
_FALLBACK_MAX_LONG_EDGE_OPTIONS = [0]
_FALLBACK_OUTPUT_FORMAT_OPTIONS: list[tuple[str, str]] = [("png", "PNG"), ("jpg", "JPG")]
_FALLBACK_COLOR_PRESETS: list[tuple[str, str]] = [("白色", "#FFFFFF"), ("黑色", "#111111")]
_FALLBACK_DEFAULT_FIELD_TAG = "EXIF:Model"
_FALLBACK_TAG_OPTIONS: list[tuple[str, str]] = [("机身型号 (EXIF)", "EXIF:Model")]
_FALLBACK_SAMPLE_RAW_METADATA: dict[str, Any] = {}


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


def load_editor_options() -> dict[str, Any]:
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


_EDITOR_OPTIONS = load_editor_options()
STYLE_OPTIONS: tuple[str, ...] = _EDITOR_OPTIONS["style_options"]
RATIO_OPTIONS: list[tuple[str, float | None]] = _EDITOR_OPTIONS["ratio_options"]
MAX_LONG_EDGE_OPTIONS: list[int] = _EDITOR_OPTIONS["max_long_edge_options"]
OUTPUT_FORMAT_OPTIONS: list[tuple[str, str]] = _EDITOR_OPTIONS["output_format_options"]
COLOR_PRESETS: list[tuple[str, str]] = _EDITOR_OPTIONS["color_presets"]
DEFAULT_FIELD_TAG: str = _EDITOR_OPTIONS["default_field_tag"]
TAG_OPTIONS: list[tuple[str, str]] = _EDITOR_OPTIONS["tag_options"]
SAMPLE_RAW_METADATA: dict[str, Any] = _EDITOR_OPTIONS["sample_raw_metadata"]
