from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable

from app_common.report_db import PHOTO_COLUMNS
from birdstamp.meta.normalize import format_settings_line, normalize_metadata

# 与 editor_utils 中一致：不写入 context 的路径列
_REPORT_DB_PATH_COLUMNS = frozenset({
    "original_path", "current_path", "temp_jpeg_path", "debug_crop_path", "yolo_debug_path",
})

_PHOTO_AUTHOR_KEY_CANDIDATES: tuple[str, ...] = (
    "XMP-dc:Creator",
    "XMP:Creator",
    "Creator",
    "EXIF:Artist",
    "Artist",
    "IPTC:By-line",
    "By-line",
    "Author",
)


TemplateContext = Dict[str, str]


@runtime_checkable
class TemplateContextProvider(Protocol):
    """用于填充模板渲染/预览所需上下文的提供器接口。"""

    @property
    def id(self) -> str:  # pragma: no cover - simple attribute
        ...

    def provide(self, path: Path, raw_metadata: Dict[str, Any], context: TemplateContext) -> None:
        """根据给定图片路径和原始 metadata 填充/更新 context。"""
        ...


@dataclass
class _Registry:
    providers: List[TemplateContextProvider]


_REGISTRY = _Registry(providers=[])

_REPORT_DB_ROW_RESOLVER: Optional[Callable[[Path], Optional[Dict[str, Any]]]] = None


def _normalize_lookup(raw: Dict[str, Any]) -> Dict[str, Any]:
    lookup: Dict[str, Any] = {}
    for key, value in raw.items():
        key_text = str(key or "").strip().lower()
        if not key_text:
            continue
        lookup.setdefault(key_text, value)
        if ":" in key_text:
            lookup.setdefault(key_text.split(":")[-1], value)
    return lookup


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        for codec in ("utf-8", "utf-16le", "latin1"):
            try:
                value = value.decode(codec, errors="ignore")
                break
            except Exception:
                continue
    if isinstance(value, (list, tuple)):
        text_items = [_clean_text(item) for item in value]
        return " ".join(item for item in text_items if item).strip()
    if isinstance(value, dict):
        text_items = [_clean_text(item) for item in value.values()]
        return " ".join(item for item in text_items if item).strip()
    text = str(value).replace("\x00", " ").strip()
    return re.sub(r"\s+", " ", text)


def _parse_datetime_value(value: Any) -> datetime | None:
    text = _clean_text(value)
    if not text:
        return None
    normalized = text.replace("T", " ").strip()
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    for pattern in (
        "%Y:%m:%d %H:%M:%S%z",
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _extract_capture_date_text(path: Path, raw_metadata: Dict[str, Any]) -> str:
    lookup = _normalize_lookup(raw_metadata)
    for key in (
        "DateTimeOriginal",
        "CreateDate",
        "DateTimeCreated",
        "DateCreated",
        "MediaCreateDate",
    ):
        value = lookup.get(key.lower())
        dt = _parse_datetime_value(value)
        if dt is not None:
            return dt.strftime("%Y-%m-%d")
    try:
        return datetime.fromtimestamp(path.stat().st_ctime).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _extract_author_text(raw_metadata: Dict[str, Any]) -> str:
    lookup = _normalize_lookup(raw_metadata)
    for key in _PHOTO_AUTHOR_KEY_CANDIDATES:
        value = lookup.get(key.lower())
        text = _clean_text(value)
        if text:
            return text
    for key, value in raw_metadata.items():
        key_text = str(key or "").strip().lower()
        if any(token in key_text for token in ("creator", "artist", "author", "by-line")):
            text = _clean_text(value)
            if text:
                return text
    return ""


def register_template_context_provider(provider: TemplateContextProvider) -> None:
    """注册一个 TemplateContextProvider，供后续构建上下文时使用。"""
    if provider not in _REGISTRY.providers:
        _REGISTRY.providers.append(provider)


def list_template_context_providers() -> List[TemplateContextProvider]:
    """返回当前已注册的所有 TemplateContextProvider 列表（只读副本）。"""
    return list(_REGISTRY.providers)


def set_report_db_row_resolver(
    resolver: Optional[Callable[[Path], Optional[Dict[str, Any]]]]
) -> None:
    """设置全局 report.db 行解析函数（由 GUI 层注入）。

    - resolver(path) 返回与给定图片路径对应的 report 行（dict），或 None。
    - 传入 None 将禁用 report.db provider 的行解析。
    """
    global _REPORT_DB_ROW_RESOLVER
    _REPORT_DB_ROW_RESOLVER = resolver


def get_report_db_row_for_path(path: Path) -> Optional[Dict[str, Any]]:
    """根据图片路径查询 report.db 中对应的行（若配置了 resolver）。"""
    resolver = _REPORT_DB_ROW_RESOLVER
    if resolver is None:
        return None
    try:
        return resolver(path)
    except Exception:
        return None


class ExifMetadataContextProvider:
    """基于 normalize_metadata 的默认上下文提供器。

    负责填充：
    - bird
    - capture_text
    - location
    - gps_text
    - camera
    - lens
    - settings_text
    以及后续可能扩展的鸟类相关字段（如 bird_latin 等）。
    """

    def __init__(
        self,
        *,
        bird_priority: List[str] | None = None,
        bird_regex: str = r"(?P<bird>[^_]+)_",
        time_format: str = "%Y-%m-%d %H:%M",
    ) -> None:
        self._id = "exif_metadata"
        self._bird_priority = list(bird_priority or ["meta", "filename"])
        self._bird_regex = bird_regex
        self._time_format = time_format

    @property
    def id(self) -> str:
        return self._id

    def provide(self, path: Path, raw_metadata: Dict[str, Any], context: TemplateContext) -> None:
        try:
            normalized = normalize_metadata(
                path,
                raw_metadata,
                bird_arg=None,
                bird_priority=self._bird_priority,
                bird_regex=self._bird_regex,
                time_format=self._time_format,
            )
        except Exception:
            return

        context["bird"] = normalized.bird or context.get("bird", "") or ""
        context["capture_text"] = normalized.capture_text or context.get("capture_text", "") or ""
        context["location"] = normalized.location or context.get("location", "") or ""
        context["gps_text"] = normalized.gps_text or context.get("gps_text", "") or ""
        context["camera"] = normalized.camera or context.get("camera", "") or ""
        context["lens"] = normalized.lens or context.get("lens", "") or ""

        settings = normalized.settings_text or format_settings_line(normalized, show_eq_focal=True) or ""
        if settings:
            context["settings_text"] = settings


class PhotoFileTemplateContextProvider:
    """从照片文件元数据中提供模板字段，如拍摄日期与作者。"""

    def __init__(self) -> None:
        self._id = "photo_file"

    @property
    def id(self) -> str:
        return self._id

    def provide(self, path: Path, raw_metadata: Dict[str, Any], context: TemplateContext) -> None:
        capture_date = _extract_capture_date_text(path, raw_metadata)
        if capture_date:
            context["capture_date"] = capture_date

        author = _extract_author_text(raw_metadata)
        if author:
            context["author"] = author


class ReportDBTemplateContextProvider:
    """从 report.db 中读取鸟种等字段并填充模板上下文的提供器。"""

    def __init__(self) -> None:
        self._id = "report_db"

    @property
    def id(self) -> str:
        return self._id

    def provide(self, path: Path, raw_metadata: Dict[str, Any], context: TemplateContext) -> None:  # noqa: ARG002
        row = get_report_db_row_for_path(path)
        if not isinstance(row, dict):
            return

        species_cn = str(row.get("bird_species_cn") or "").strip()
        species_en = str(row.get("bird_species_en") or "").strip()

        if species_cn:
            context["bird"] = species_cn
            context["bird_common"] = species_cn
        if species_en:
            context.setdefault("bird_latin", species_en)
            context.setdefault("bird_scientific", species_en)

        # 非路径列统一以 report.<列名> 写入，供模板 data_source=report_db 时使用
        for (col_name, _type_def, _default) in PHOTO_COLUMNS:
            if col_name in _REPORT_DB_PATH_COLUMNS:
                continue
            val = row.get(col_name)
            context["report." + col_name] = "" if val is None else str(val).strip()


def _ensure_default_providers_registered() -> None:
    if not any(p.id == "exif_metadata" for p in _REGISTRY.providers):
        register_template_context_provider(ExifMetadataContextProvider())
    if not any(p.id == "photo_file" for p in _REGISTRY.providers):
        register_template_context_provider(PhotoFileTemplateContextProvider())
    if not any(p.id == "report_db" for p in _REGISTRY.providers):
        register_template_context_provider(ReportDBTemplateContextProvider())


def build_template_context(path: Path, raw_metadata: Dict[str, Any]) -> TemplateContext:
    """构建模板渲染与 UI 预览所需的上下文字典。

    - 基础字段（不依赖提供器）：
      - stem / filename
    - 其余字段由已注册的 TemplateContextProvider 逐个填充。
    """
    _ensure_default_providers_registered()

    context: TemplateContext = {
        "bird": "",
        "capture_date": "",
        "capture_text": "",
        "author": "",
        "location": "",
        "gps_text": "",
        "camera": "",
        "lens": "",
        "settings_text": "",
        "stem": path.stem,
        "filename": path.name,
    }

    for provider in list_template_context_providers():
        try:
            provider.provide(path, raw_metadata, context)
        except Exception:
            continue
    return context

