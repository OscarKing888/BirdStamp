"""editor_photo_list.py – standalone PhotoListWidget."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTreeWidget,
    QTreeWidgetItem,
)

from birdstamp.constants import SUPPORTED_EXTENSIONS
from birdstamp.discover import discover_inputs
from birdstamp.gui.editor_utils import path_key as _path_key

class PhotoListWidget(QTreeWidget):
    pathsDropped = pyqtSignal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setColumnCount(4)
        self.setHeaderLabels(["照片", "Title", "裁切比例", "标星"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.resizeSection(0, 260)
        header.resizeSection(1, 160)
        header.resizeSection(2, 96)
        header.resizeSection(3, 88)

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

