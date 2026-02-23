"""editor_photo_list.py – QTreeWidget-compatible adapter on top of FileListPanel."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt6.QtCore import QEvent, QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QProgressBar,
    QSlider,
    QToolButton,
    QTreeWidgetItem,
)

from app_common.file_browser import FileListPanel
from birdstamp.constants import SUPPORTED_EXTENSIONS
from birdstamp.discover import discover_inputs
from birdstamp.gui.editor_utils import path_key as _path_key


class PhotoListWidget(FileListPanel):
    """
    兼容旧版 `QTreeWidget` 调用方式的适配层。

    设计目的：
    - 主编辑器仍按 `QTreeWidget` API 使用（`addTopLevelItem` / `selectedItems` / `currentItemChanged` 等）
    - 底层实际使用 `FileListPanel` 的列表视图与样式实现
    - 隐藏 `FileListPanel` 的目录浏览专用增强 UI（缩略图切换、过滤栏、进度条）
    """

    pathsDropped = pyqtSignal(list)
    currentItemChanged = pyqtSignal(object, object)  # (QTreeWidgetItem | None, QTreeWidgetItem | None)

    def __init__(self) -> None:
        super().__init__()
        self._configure_editor_compat_view()
        self._install_drop_event_filters()
        self._tree_widget.currentItemChanged.connect(self._emit_current_item_changed)

    # ------------------------------------------------------------------
    # Compatibility setup
    # ------------------------------------------------------------------

    def _configure_editor_compat_view(self) -> None:
        # 强制使用列表模式，避免主编辑器使用 QTreeWidget API 时与缩略图模式语义冲突。
        self._set_view_mode(self._MODE_LIST)

        # 隐藏 FileListPanel 扩展 UI（仍保留底层树控件）。
        self._hide_non_tree_ui()

        # 将 FileListPanel 的 7 列配置收敛为主编辑器当前使用的 4 列。
        self._tree_widget.setColumnCount(4)
        self._tree_widget.setHeaderLabels(["照片", "Title", "裁切比例", "标星"])
        self._tree_widget.setSortingEnabled(False)
        self._tree_widget.setAcceptDrops(True)
        self._tree_widget.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

        header = self._tree_widget.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 260)
        header.resizeSection(1, 160)
        header.resizeSection(2, 96)
        header.resizeSection(3, 88)

        # 兼容旧控件的默认行为
        self._tree_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree_widget.setRootIsDecorated(False)
        self._tree_widget.setUniformRowHeights(True)

    def _hide_non_tree_ui(self) -> None:
        # 隐藏已知控件
        for widget in (
            getattr(self, "_btn_list", None),
            getattr(self, "_btn_thumb", None),
            getattr(self, "_size_slider", None),
            getattr(self, "_size_label", None),
            getattr(self, "_filter_edit", None),
            getattr(self, "_btn_filter_pick", None),
            getattr(self, "_meta_progress", None),
            getattr(self, "_list_widget", None),  # 锁定列表模式，不暴露缩略图
        ):
            if widget is not None:
                widget.hide()
        for btn in getattr(self, "_star_btns", []) or []:
            try:
                btn.hide()
            except Exception:
                pass

        # 隐藏 `FileListPanel` 顶部布局中未缓存引用的标签（如“大小:”）。
        for label in self.findChildren(QLabel):
            if label is None:
                continue
            if label is getattr(self, "_size_label", None):
                continue
            text = (label.text() or "").strip()
            if text in {"大小:"}:
                label.hide()

        # 隐藏进度条后也禁止后台加载器误触发时闪烁
        if isinstance(getattr(self, "_meta_progress", None), QProgressBar):
            self._meta_progress.hide()

        # 兜底：若尺寸滑块仍占位，收起其高度
        if isinstance(getattr(self, "_size_slider", None), QSlider):
            self._size_slider.setFixedHeight(0)
        if isinstance(getattr(self, "_btn_list", None), QToolButton):
            self._btn_list.setFixedHeight(0)
        if isinstance(getattr(self, "_btn_thumb", None), QToolButton):
            self._btn_thumb.setFixedHeight(0)

    def _install_drop_event_filters(self) -> None:
        self.setAcceptDrops(True)
        self._tree_widget.setAcceptDrops(True)
        try:
            self._tree_widget.viewport().setAcceptDrops(True)
        except Exception:
            pass
        self.installEventFilter(self)
        self._tree_widget.installEventFilter(self)
        try:
            self._tree_widget.viewport().installEventFilter(self)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Signal bridge
    # ------------------------------------------------------------------

    def _emit_current_item_changed(self, current: object, previous: object) -> None:
        self.currentItemChanged.emit(current, previous)

    # ------------------------------------------------------------------
    # Drag-and-drop (compat with old PhotoListWidget)
    # ------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        event_type = event.type()
        viewport = getattr(self._tree_widget, "viewport", lambda: None)()
        is_drop_target = watched in {self, self._tree_widget} or watched is viewport
        if not is_drop_target:
            return super().eventFilter(watched, event)

        if event_type == QEvent.Type.DragEnter:
            if getattr(event, "mimeData", None) and event.mimeData().hasUrls():  # type: ignore[attr-defined]
                event.acceptProposedAction()  # type: ignore[attr-defined]
                return True
        elif event_type == QEvent.Type.DragMove:
            if getattr(event, "mimeData", None) and event.mimeData().hasUrls():  # type: ignore[attr-defined]
                event.acceptProposedAction()  # type: ignore[attr-defined]
                return True
        elif event_type == QEvent.Type.Drop:
            if getattr(event, "mimeData", None) and event.mimeData().hasUrls():  # type: ignore[attr-defined]
                deduped = self._collect_dropped_paths(event)
                if deduped:
                    self.pathsDropped.emit(deduped)
                    event.acceptProposedAction()  # type: ignore[attr-defined]
                    return True
        return super().eventFilter(watched, event)

    def _collect_dropped_paths(self, event: QEvent) -> list[Path]:
        urls = event.mimeData().urls()  # type: ignore[attr-defined]
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
        return deduped

    # ------------------------------------------------------------------
    # QTreeWidget-compatible surface used by birdstamp.gui.editor
    # ------------------------------------------------------------------

    def setSelectionMode(self, mode: Any) -> None:  # type: ignore[override]
        self._tree_widget.setSelectionMode(mode)
        try:
            self._list_widget.setSelectionMode(mode)
        except Exception:
            pass

    def header(self):  # noqa: ANN201
        return self._tree_widget.header()

    def topLevelItemCount(self) -> int:
        return int(self._tree_widget.topLevelItemCount())

    def topLevelItem(self, index: int) -> QTreeWidgetItem | None:
        return self._tree_widget.topLevelItem(index)

    def addTopLevelItem(self, item: QTreeWidgetItem) -> None:
        self._tree_widget.addTopLevelItem(item)

    def indexOfTopLevelItem(self, item: QTreeWidgetItem) -> int:
        return int(self._tree_widget.indexOfTopLevelItem(item))

    def takeTopLevelItem(self, index: int) -> QTreeWidgetItem | None:
        return self._tree_widget.takeTopLevelItem(index)

    def clear(self) -> None:  # type: ignore[override]
        try:
            self._stop_all_loaders()
        except Exception:
            pass
        self._tree_widget.clear()
        try:
            self._list_widget.clear()
        except Exception:
            pass
        self._tree_item_map = {}
        self._item_map = {}
        self._all_files = []
        self._meta_cache = {}
        self._current_dir = ""

    def currentItem(self) -> QTreeWidgetItem | None:
        return self._tree_widget.currentItem()

    def setCurrentItem(self, item: QTreeWidgetItem) -> None:
        self._tree_widget.setCurrentItem(item)

    def selectedItems(self) -> list[QTreeWidgetItem]:
        return list(self._tree_widget.selectedItems())
