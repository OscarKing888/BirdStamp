# Editor UI utilities: color, font, screen picker, placeholder, metadata context.
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageColor, ImageDraw
from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFontDatabase, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QLabel, QWidget

from birdstamp.meta.normalize import format_settings_line, normalize_metadata
from birdstamp.render.typography import list_available_font_paths, load_font

ALIGN_OPTIONS_VERTICAL = ("top", "center", "bottom")
ALIGN_OPTIONS_HORIZONTAL = ("left", "center", "right")

DEFAULT_TEMPLATE_BANNER_COLOR = "#111111"
TEMPLATE_BANNER_COLOR_NONE = "none"
TEMPLATE_BANNER_COLOR_CUSTOM = "custom"
TEMPLATE_BANNER_TOP_PADDING_PX = 16
DEFAULT_TEMPLATE_FONT_TYPE = "auto"
DEFAULT_CROP_EFFECT_ALPHA = 160


def safe_color(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    try:
        ImageColor.getrgb(text)
    except ValueError:
        return fallback
    return text


def build_color_preview_swatch() -> QLabel:
    swatch = QLabel()
    swatch.setFixedSize(24, 20)
    swatch.setAlignment(Qt.AlignmentFlag.AlignCenter)
    swatch.setStyleSheet("border: 1px solid #2A2A2A; border-radius: 2px;")
    swatch.setToolTip("")
    return swatch


def set_color_preview_swatch(
    swatch: QLabel | None,
    value: str | None,
    *,
    fallback: str = "#FFFFFF",
    allow_none: bool = False,
) -> None:
    if swatch is None:
        return
    raw = str(value or "").strip()
    lowered = raw.lower()
    if allow_none and lowered in {"", "none", "transparent", "off", "false", "0"}:
        swatch.setText("无")
        swatch.setToolTip("透明")
        swatch.setStyleSheet(
            "background: #E3E5E8; color: #4A4A4A; border: 1px dashed #7A7A7A; border-radius: 2px; font-size: 10px;"
        )
        return
    color_text = safe_color(raw, fallback).upper()
    swatch.setText("")
    swatch.setToolTip(color_text)
    swatch.setStyleSheet(f"background: {color_text}; border: 1px solid #2A2A2A; border-radius: 2px;")


def normalize_template_banner_color(value: Any, default: str = DEFAULT_TEMPLATE_BANNER_COLOR) -> str:
    fallback = safe_color(default, DEFAULT_TEMPLATE_BANNER_COLOR)
    if value is None:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    lowered = text.lower()
    if lowered in {"none", "transparent", "off", "false", "0"}:
        return TEMPLATE_BANNER_COLOR_NONE
    return safe_color(text, fallback)


def template_banner_fill_color(value: Any) -> str | None:
    color = normalize_template_banner_color(value)
    if color == TEMPLATE_BANNER_COLOR_NONE:
        return None
    return color


@lru_cache(maxsize=4096)
def font_family_label_from_path(font_path_text: str) -> str:
    path_text = str(font_path_text or "").strip()
    if not path_text:
        return ""
    try:
        font_id = QFontDatabase.addApplicationFont(path_text)
    except Exception:
        return ""
    if font_id < 0:
        return ""
    try:
        names: list[str] = []
        for family in QFontDatabase.applicationFontFamilies(font_id):
            text = str(family or "").strip()
            if text and text not in names:
                names.append(text)
        return " / ".join(names[:2])
    except Exception:
        return ""
    finally:
        try:
            QFontDatabase.removeApplicationFont(font_id)
        except Exception:
            pass


def normalize_template_font_type(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_TEMPLATE_FONT_TYPE
    lowered = text.lower()
    if lowered in {"auto", "default", "system", "none"}:
        return DEFAULT_TEMPLATE_FONT_TYPE
    return text


def template_font_path_from_type(value: Any) -> Path | None:
    font_type = normalize_template_font_type(value)
    if font_type == DEFAULT_TEMPLATE_FONT_TYPE:
        return None
    try:
        candidate = Path(font_type).expanduser()
    except Exception:
        return None
    try:
        if candidate.exists() and candidate.is_file():
            return candidate
    except Exception:
        return None
    return None


@lru_cache(maxsize=1)
def template_font_choices() -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = [("自动(系统默认)", DEFAULT_TEMPLATE_FONT_TYPE)]
    font_entries: list[tuple[str, str]] = []
    seen_paths: set[str] = set()
    for font_path in list_available_font_paths():
        key = str(font_path).strip()
        if not key or key in seen_paths:
            continue
        seen_paths.add(key)
        family_label = font_family_label_from_path(key)
        if family_label:
            label = f"{family_label} ({font_path.name})"
        else:
            label = f"{font_path.stem} ({font_path.name})"
        font_entries.append((label, key))
    font_entries.sort(key=lambda item: item[0].lower())
    choices.extend(font_entries)
    return choices


def path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).casefold()


def sanitize_template_name(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    safe = re.sub(r"[\\/:*?\"<>|]+", "_", text)
    safe = safe.replace(" ", "_").strip("._")
    return safe


def build_metadata_context(path: Path, raw_metadata: dict[str, Any]) -> dict[str, str]:
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


# 模板 fallback 可用的上下文变量列表，顺序即下拉菜单顺序
# 每项 (template_expr, label)
FALLBACK_CONTEXT_VARS: list[tuple[str, str]] = [
    ("{bird}", "鸟种名称"),
    ("{capture_text}", "拍摄日期时间"),
    ("{location}", "拍摄地点"),
    ("{gps_text}", "GPS 坐标文字"),
    ("{camera}", "相机型号"),
    ("{lens}", "镜头型号"),
    ("{settings_text}", "拍摄参数"),
    ("{stem}", "文件名（不含扩展名）"),
    ("{filename}", "完整文件名"),
]


def pil_to_qpixmap(image: Image.Image) -> QPixmap:
    """Convert a PIL Image to a QPixmap (RGBA round-trip)."""
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    q_image = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(q_image.copy())


def build_placeholder_image(width: int = 1600, height: int = 1000) -> Image.Image:
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


# -------- Screen color picker (Qt) --------
_ACTIVE_SCREEN_COLOR_PICKERS: list["_ScreenColorPickerSession"] = []


def _sample_screen_color_at(global_pos: QPoint) -> str | None:
    screen = QGuiApplication.screenAt(global_pos)
    if screen is None:
        screen = QGuiApplication.primaryScreen()
    if screen is None:
        return None
    geo = screen.geometry()
    local_x = global_pos.x() - geo.x()
    local_y = global_pos.y() - geo.y()
    if local_x < 0 or local_y < 0:
        return None
    sample = screen.grabWindow(0, local_x, local_y, 1, 1)
    if sample.isNull():
        return None
    image = sample.toImage()
    if image.isNull():
        return None
    color = QColor.fromRgb(image.pixel(0, 0))
    return color.name(QColor.NameFormat.HexRgb).upper()


class _ScreenColorPickerOverlay(QWidget):
    colorPicked = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, geometry: QRect, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(geometry)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            color = _sample_screen_color_at(event.globalPosition().toPoint())
            if color:
                self.colorPicked.emit(color)
            else:
                self.cancelled.emit()
            return
        if event.button() in {Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton}:
            self.cancelled.emit()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        _ = event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 26))
        pos = self.mapFromGlobal(QCursor.pos())
        sample = _sample_screen_color_at(QCursor.pos())
        sample_color = QColor(sample) if sample else QColor("#FFFFFF")
        preview_size = 32
        preview_rect = QRectF(
            float(pos.x() + 16),
            float(pos.y() + 16),
            float(preview_size),
            float(preview_size),
        )
        if preview_rect.right() > self.width() - 8:
            preview_rect.moveLeft(float(max(8, pos.x() - preview_size - 16)))
        if preview_rect.bottom() > self.height() - 8:
            preview_rect.moveTop(float(max(8, pos.y() - preview_size - 16)))
        painter.setPen(QPen(QColor("#111111"), 1))
        painter.setBrush(sample_color)
        painter.drawRect(preview_rect)
        text = f"{sample or '-'}  左键取色 / 右键或Esc取消"
        text_rect = QRectF(
            preview_rect.left(),
            preview_rect.bottom() + 6.0,
            280.0,
            22.0,
        )
        if text_rect.right() > self.width() - 8:
            text_rect.moveLeft(float(max(8, self.width() - text_rect.width() - 8)))
        if text_rect.bottom() > self.height() - 8:
            text_rect.moveTop(float(max(8, preview_rect.top() - text_rect.height() - 6.0)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 20, 180))
        painter.drawRoundedRect(text_rect, 4.0, 4.0)
        painter.setPen(QPen(QColor("#F6F6F6"), 1))
        painter.drawText(text_rect.adjusted(8.0, 0.0, -8.0, 0.0), int(Qt.AlignmentFlag.AlignVCenter), text)
        painter.end()


class _ScreenColorPickerSession:
    def __init__(self, *, parent: QWidget | None, on_picked: Callable[[str], None]) -> None:
        self._parent = parent
        self._on_picked = on_picked
        self._overlays: list[_ScreenColorPickerOverlay] = []
        self._finished = False

    def start(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        for screen in screens:
            overlay = _ScreenColorPickerOverlay(screen.geometry(), parent=None)
            overlay.colorPicked.connect(self._handle_color_picked)
            overlay.cancelled.connect(self._handle_cancelled)
            self._overlays.append(overlay)
        _ACTIVE_SCREEN_COLOR_PICKERS.append(self)
        for overlay in self._overlays:
            overlay.show()
            overlay.raise_()
        if self._overlays:
            self._overlays[0].activateWindow()

    def _finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        for overlay in self._overlays:
            overlay.hide()
            overlay.deleteLater()
        self._overlays.clear()
        if self in _ACTIVE_SCREEN_COLOR_PICKERS:
            _ACTIVE_SCREEN_COLOR_PICKERS.remove(self)

    def _handle_color_picked(self, color: str) -> None:
        self._finish()
        try:
            self._on_picked(color)
        except Exception:
            return

    def _handle_cancelled(self) -> None:
        self._finish()


def start_screen_color_picker(*, parent: QWidget | None, on_picked: Callable[[str], None]) -> None:
    session = _ScreenColorPickerSession(parent=parent, on_picked=on_picked)
    session.start()
