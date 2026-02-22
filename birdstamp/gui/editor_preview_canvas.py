"""editor_preview_canvas.py – standalone PreviewCanvas widget."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QWidget

from birdstamp.gui.editor_utils import DEFAULT_CROP_EFFECT_ALPHA as _DEFAULT_CROP_EFFECT_ALPHA

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

