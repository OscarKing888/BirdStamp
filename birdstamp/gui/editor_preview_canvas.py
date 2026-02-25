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

from dataclasses import dataclass

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QWidget

from app_common.preview_canvas import PreviewCanvas, PreviewOverlayOptions, PreviewOverlayState
from birdstamp.gui.editor_utils import DEFAULT_CROP_EFFECT_ALPHA as _DEFAULT_CROP_EFFECT_ALPHA

NormalizedBox = tuple[float, float, float, float]


@dataclass(slots=True)
class EditorPreviewOverlayState(PreviewOverlayState):
    """Editor-specific overlay payloads.

    Extends the base preview overlay state (focus box) with editor overlays.
    """

    bird_box: "NormalizedBox | None" = None
    crop_effect_box: "NormalizedBox | None" = None


@dataclass(slots=True)
class EditorPreviewOverlayOptions(PreviewOverlayOptions):
    """Editor-specific preview overlay options."""

    show_bird_box: bool = False
    show_crop_effect: bool = False
    crop_effect_alpha: int = _DEFAULT_CROP_EFFECT_ALPHA


class EditorPreviewCanvas(PreviewCanvas):
    """PreviewCanvas specialised for the BirdStamp photo editor.

    Adds bird-detection-box and crop-effect-shade overlays on top of the
    base class capabilities.  All setter method names are kept identical to
    the previous monolithic implementation for drop-in compatibility.
    """

    def __init__(
        self,
        parent: "QWidget | None" = None,
        *,
        placeholder_text: str = "暂无预览",
    ) -> None:
        super().__init__(parent, placeholder_text=placeholder_text)
        self._bird_box: "NormalizedBox | None" = None
        self._show_bird_box: bool = False
        self._crop_effect_box: "NormalizedBox | None" = None
        self._show_crop_effect: bool = False
        self._crop_effect_alpha: int = _DEFAULT_CROP_EFFECT_ALPHA

    # ------------------------------------------------------------------
    # Public API – bird box
    # ------------------------------------------------------------------

    def set_bird_box(self, bird_box: "NormalizedBox | None") -> None:
        if self._set_bird_box_no_update(bird_box):
            self.update()

    def set_show_bird_box(self, enabled: bool) -> None:
        if self._set_show_bird_box_no_update(enabled):
            self.update()

    # ------------------------------------------------------------------
    # Public API – crop-effect shade
    # ------------------------------------------------------------------

    def set_crop_effect_box(self, crop_effect_box: "NormalizedBox | None") -> None:
        if self._set_crop_effect_box_no_update(crop_effect_box):
            self.update()

    def set_show_crop_effect(self, enabled: bool) -> None:
        if self._set_show_crop_effect_no_update(enabled):
            self.update()

    def set_crop_effect_alpha(self, alpha: int) -> None:
        if self._set_crop_effect_alpha_no_update(alpha):
            self.update()

    # ------------------------------------------------------------------
    # Extension hooks
    # ------------------------------------------------------------------

    def _apply_overlay_state_data(self, state: "PreviewOverlayState") -> bool:
        changed = super()._apply_overlay_state_data(state)
        if not isinstance(state, EditorPreviewOverlayState):
            return changed
        if self._set_bird_box_no_update(state.bird_box):
            changed = True
        if self._set_crop_effect_box_no_update(state.crop_effect_box):
            changed = True
        return changed

    def _apply_overlay_options_data(self, options: "PreviewOverlayOptions") -> bool:
        changed = super()._apply_overlay_options_data(options)
        if not isinstance(options, EditorPreviewOverlayOptions):
            return changed
        if self._set_show_bird_box_no_update(options.show_bird_box):
            changed = True
        if self._set_show_crop_effect_no_update(options.show_crop_effect):
            changed = True
        if self._set_crop_effect_alpha_no_update(options.crop_effect_alpha):
            changed = True
        return changed

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

    def _set_bird_box_no_update(self, bird_box: "NormalizedBox | None") -> bool:
        if self._bird_box == bird_box:
            return False
        self._bird_box = bird_box
        return True

    def _set_show_bird_box_no_update(self, enabled: bool) -> bool:
        parsed = bool(enabled)
        if self._show_bird_box == parsed:
            return False
        self._show_bird_box = parsed
        return True

    def _set_crop_effect_box_no_update(self, crop_effect_box: "NormalizedBox | None") -> bool:
        if self._crop_effect_box == crop_effect_box:
            return False
        self._crop_effect_box = crop_effect_box
        return True

    def _set_show_crop_effect_no_update(self, enabled: bool) -> bool:
        parsed = bool(enabled)
        if self._show_crop_effect == parsed:
            return False
        self._show_crop_effect = parsed
        return True

    def _set_crop_effect_alpha_no_update(self, alpha: int) -> bool:
        parsed = max(0, min(255, int(alpha)))
        if parsed == self._crop_effect_alpha:
            return False
        self._crop_effect_alpha = parsed
        return True

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
