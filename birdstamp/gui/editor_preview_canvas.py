# -*- coding: utf-8 -*-
"""editor_preview_canvas.py – BirdStamp editor's PreviewCanvas subclass.

Extends ``app_common.preview_canvas.PreviewCanvas`` with two editor-specific
overlays:

* **Bird detection box** – semi-transparent blue fill + border.
* **Crop-effect shade** – darkened path outside the intended crop rectangle.

All other behaviour (checker background, focus box, zoom/pan, original-size
mode) is inherited from the base class.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from app_common.preview_canvas import PreviewCanvas
from birdstamp.gui.editor_utils import DEFAULT_CROP_EFFECT_ALPHA as _DEFAULT_CROP_EFFECT_ALPHA


class EditorPreviewCanvas(PreviewCanvas):
    """PreviewCanvas specialised for the BirdStamp photo editor.

    Adds bird-detection-box and crop-effect-shade overlays on top of the
    base class capabilities.  All setter method names are kept identical to
    the previous monolithic implementation for drop-in compatibility.
    """

    def __init__(self, parent: "QWidget | None" = None) -> None:
        super().__init__(parent)
        self._bird_box: "tuple[float, float, float, float] | None" = None
        self._show_bird_box: bool = False
        self._crop_effect_box: "tuple[float, float, float, float] | None" = None
        self._show_crop_effect: bool = False
        self._crop_effect_alpha: int = _DEFAULT_CROP_EFFECT_ALPHA

    # ------------------------------------------------------------------
    # Public API – bird box
    # ------------------------------------------------------------------

    def set_bird_box(self, bird_box: "tuple[float, float, float, float] | None") -> None:
        self._bird_box = bird_box
        self.update()

    def set_show_bird_box(self, enabled: bool) -> None:
        self._show_bird_box = bool(enabled)
        self.update()

    # ------------------------------------------------------------------
    # Public API – crop-effect shade
    # ------------------------------------------------------------------

    def set_crop_effect_box(self, crop_effect_box: "tuple[float, float, float, float] | None") -> None:
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

    # ------------------------------------------------------------------
    # Extension hooks
    # ------------------------------------------------------------------

    def _on_source_cleared(self) -> None:
        self._bird_box = None
        self._crop_effect_box = None

    def _paint_overlays(self, painter, draw_rect, content_rect) -> None:  # type: ignore[override]
        if self._show_bird_box and self._bird_box:
            self._paint_bird_overlay(painter, draw_rect, content_rect)
        if self._show_crop_effect and self._crop_effect_box:
            self._paint_crop_shade(painter, draw_rect, content_rect)

    # ------------------------------------------------------------------
    # Private overlay painters
    # ------------------------------------------------------------------

    def _paint_bird_overlay(self, painter, draw_rect: "QRectF", content_rect) -> None:
        bb = self._bird_box
        if bb is None:
            return
        bl = draw_rect.left() + bb[0] * draw_rect.width()
        bt = draw_rect.top() + bb[1] * draw_rect.height()
        br = draw_rect.left() + bb[2] * draw_rect.width()
        bbot = draw_rect.top() + bb[3] * draw_rect.height()
        bird_rect = QRectF(
            min(bl, br), min(bt, bbot),
            abs(br - bl), abs(bbot - bt),
        ).intersected(QRectF(content_rect))
        if bird_rect.width() < 1.0 or bird_rect.height() < 1.0:
            return

        fill = QColor("#A9DBFF")
        fill.setAlpha(96)
        painter.fillRect(bird_rect, fill)

        pen = QPen(QColor("#8BCBFF"))
        pen.setWidth(1)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawRect(bird_rect)

    def _paint_crop_shade(self, painter, draw_rect: "QRectF", content_rect) -> None:
        cb = self._crop_effect_box
        if cb is None:
            return
        cl = draw_rect.left() + cb[0] * draw_rect.width()
        ct = draw_rect.top() + cb[1] * draw_rect.height()
        cr = draw_rect.left() + cb[2] * draw_rect.width()
        cbot = draw_rect.top() + cb[3] * draw_rect.height()
        crop_rect = QRectF(
            min(cl, cr), min(ct, cbot),
            abs(cr - cl), abs(cbot - ct),
        )
        visible_rect = draw_rect.intersected(QRectF(content_rect))
        crop_rect = crop_rect.intersected(visible_rect)
        if visible_rect.width() < 1.0 or visible_rect.height() < 1.0:
            return
        if crop_rect.width() < 1.0 or crop_rect.height() < 1.0:
            return

        shade_path = QPainterPath()
        shade_path.addRect(visible_rect)
        keep_path = QPainterPath()
        keep_path.addRect(crop_rect)
        painter.fillPath(shade_path.subtracted(keep_path), QColor(0, 0, 0, self._crop_effect_alpha))


# ---------------------------------------------------------------------------
# Backward-compatible alias: code that imports PreviewCanvas from this module
# continues to work without changes.
# ---------------------------------------------------------------------------
PreviewCanvas = EditorPreviewCanvas  # type: ignore[misc]
