from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageColor
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QColor, QImage, QKeySequence, QPalette, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from birdstamp.constants import DEFAULT_SHOW_FIELDS, SUPPORTED_EXTENSIONS, VALID_FRAME_STYLES, VALID_MODES
from birdstamp.decoders.image_decoder import decode_image
from birdstamp.meta.exiftool import extract_many
from birdstamp.meta.normalize import normalize_metadata
from birdstamp.meta.pillow_fallback import extract_pillow_metadata
from birdstamp.models import NormalizedMetadata, RenderOptions, RenderTemplate
from birdstamp.render.banner import render_banner
from birdstamp.render.image_modes import apply_output_mode
from birdstamp.template_loader import THEME_OVERRIDES, list_builtin_templates, load_template, normalize_template_dict

SHOW_FIELD_ORDER = ["bird", "time", "location", "gps", "camera", "lens", "settings"]
DEFAULT_BIRD_REGEX = r"(?P<bird>[^_]+)_"


def _safe_color(value: str, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    try:
        ImageColor.getrgb(text)
    except ValueError:
        return fallback
    return text


def _pil_to_qpixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    q_image = QImage(data, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(q_image.copy())


class BirdStampEditorWindow(QMainWindow):
    def __init__(self, startup_file: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("BirdStamp Editor")
        self.resize(1580, 940)
        self.setMinimumSize(1260, 760)

        self.base_image: Image.Image | None = None
        self.last_rendered: Image.Image | None = None
        self.preview_pixmap: QPixmap | None = None
        self.image_path: Path | None = None
        self.raw_metadata: dict[str, Any] = {}

        self._setup_ui()
        self._setup_shortcuts()
        self._apply_system_adaptive_style()
        self._load_template_by_name("default")
        self._set_status("Ready. Open an image to start.")

        if startup_file:
            self.open_image(startup_file)

    def _setup_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root_layout.addWidget(splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(430)
        left_scroll.setMaximumWidth(520)

        left_panel = QWidget()
        left_scroll.setWidget(left_panel)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(6, 6, 6, 6)
        left_layout.setSpacing(10)

        self._build_input_group(left_layout)
        self._build_template_group(left_layout)
        self._build_render_group(left_layout)
        self._build_fields_group(left_layout)
        left_layout.addStretch(1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        action_row = QHBoxLayout()
        open_button = QPushButton("Open Image")
        open_button.clicked.connect(self.pick_image)
        action_row.addWidget(open_button)

        preview_button = QPushButton("Update Preview")
        preview_button.clicked.connect(self.render_preview)
        action_row.addWidget(preview_button)

        export_button = QPushButton("Export")
        export_button.clicked.connect(self.export_rendered)
        action_row.addWidget(export_button)

        save_tpl_button = QPushButton("Save Template")
        save_tpl_button.clicked.connect(self.save_template)
        action_row.addWidget(save_tpl_button)
        action_row.addStretch(1)
        right_layout.addLayout(action_row)

        self.preview_label = QLabel("Open an image to preview.")
        self.preview_label.setObjectName("PreviewLabel")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.preview_label, stretch=1)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([470, 1110])

        self.setStatusBar(self.statusBar())

    def _build_input_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Input")
        parent_layout.addWidget(group)
        layout = QVBoxLayout(group)
        layout.setSpacing(6)

        row = QHBoxLayout()
        open_btn = QPushButton("Open Image")
        open_btn.clicked.connect(self.pick_image)
        row.addWidget(open_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("Image path")
        layout.addWidget(self.path_edit)

        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        self.meta_text.setMinimumHeight(125)
        self.meta_text.setPlaceholderText("Metadata summary")
        layout.addWidget(self.meta_text)

    def _build_template_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Template")
        parent_layout.addWidget(group)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        self.template_combo = QComboBox()
        self.template_combo.addItems(list_builtin_templates())
        self.template_combo.currentTextChanged.connect(self._load_template_by_name)
        top_row.addWidget(self.template_combo, stretch=1)
        load_file_btn = QPushButton("Load File")
        load_file_btn.clicked.connect(self.load_template_file)
        top_row.addWidget(load_file_btn)
        layout.addLayout(top_row)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        self.template_name_input = QLineEdit("default")
        form.addRow("Name", self.template_name_input)

        theme_row = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(sorted(THEME_OVERRIDES.keys()))
        self.theme_combo.setCurrentText("gray")
        theme_row.addWidget(self.theme_combo, stretch=1)
        apply_theme_btn = QPushButton("Apply")
        apply_theme_btn.clicked.connect(self.apply_theme_colors)
        theme_row.addWidget(apply_theme_btn)
        theme_wrap = QWidget()
        theme_wrap.setLayout(theme_row)
        form.addRow("Theme", theme_wrap)

        self.banner_height_spin = QSpinBox()
        self.banner_height_spin.setRange(80, 1200)
        self.banner_height_spin.setValue(220)
        form.addRow("Banner Height", self.banner_height_spin)

        self.left_ratio_spin = QDoubleSpinBox()
        self.left_ratio_spin.setRange(0.3, 0.8)
        self.left_ratio_spin.setDecimals(2)
        self.left_ratio_spin.setSingleStep(0.01)
        self.left_ratio_spin.setValue(0.58)
        form.addRow("Left Ratio", self.left_ratio_spin)

        self.padding_x_spin = QSpinBox()
        self.padding_x_spin.setRange(8, 300)
        self.padding_x_spin.setValue(48)
        form.addRow("Padding X", self.padding_x_spin)

        self.padding_y_spin = QSpinBox()
        self.padding_y_spin.setRange(8, 300)
        self.padding_y_spin.setValue(24)
        form.addRow("Padding Y", self.padding_y_spin)

        self.title_font_spin = QSpinBox()
        self.title_font_spin.setRange(10, 300)
        self.title_font_spin.setValue(56)
        form.addRow("Title Font", self.title_font_spin)

        self.body_font_spin = QSpinBox()
        self.body_font_spin.setRange(10, 300)
        self.body_font_spin.setValue(32)
        form.addRow("Body Font", self.body_font_spin)

        self.small_font_spin = QSpinBox()
        self.small_font_spin.setRange(8, 300)
        self.small_font_spin.setValue(22)
        form.addRow("Small Font", self.small_font_spin)

        self.divider_check = QCheckBox("Show Divider")
        self.divider_check.setChecked(True)
        form.addRow("", self.divider_check)

        self.logo_input = QLineEdit("BirdStamp")
        form.addRow("Logo", self.logo_input)

        self.color_inputs: dict[str, QLineEdit] = {}
        self.color_inputs["background"] = self._add_color_editor(form, "Color BG", "#F2F2F2")
        self.color_inputs["text"] = self._add_color_editor(form, "Color Text", "#111111")
        self.color_inputs["muted"] = self._add_color_editor(form, "Color Muted", "#4A4A4A")
        self.color_inputs["divider"] = self._add_color_editor(form, "Color Divider", "#D0D0D0")

        layout.addLayout(form)

    def _build_render_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Render")
        parent_layout.addWidget(group)
        form = QFormLayout(group)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(sorted(VALID_MODES))
        self.mode_combo.setCurrentText("keep")
        form.addRow("Mode", self.mode_combo)

        self.frame_style_combo = QComboBox()
        self.frame_style_combo.addItems(sorted(VALID_FRAME_STYLES))
        self.frame_style_combo.setCurrentText("crop")
        form.addRow("Frame Style", self.frame_style_combo)

        self.max_long_edge_spin = QSpinBox()
        self.max_long_edge_spin.setRange(256, 10000)
        self.max_long_edge_spin.setValue(2048)
        form.addRow("Max Long Edge", self.max_long_edge_spin)

        self.bird_override_input = QLineEdit()
        self.bird_override_input.setPlaceholderText("Optional override")
        form.addRow("Bird", self.bird_override_input)

        self.show_eq_focal_check = QCheckBox("Show 35mm Equivalent")
        self.show_eq_focal_check.setChecked(True)
        form.addRow("", self.show_eq_focal_check)

    def _build_fields_group(self, parent_layout: QVBoxLayout) -> None:
        group = QGroupBox("Fields")
        parent_layout.addWidget(group)
        layout = QGridLayout(group)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(4)

        self.show_field_checks: dict[str, QCheckBox] = {}
        for idx, name in enumerate(SHOW_FIELD_ORDER):
            check = QCheckBox(name)
            check.setChecked(name in DEFAULT_SHOW_FIELDS)
            self.show_field_checks[name] = check
            layout.addWidget(check, idx // 2, idx % 2)

    def _add_color_editor(self, form: QFormLayout, label: str, default: str) -> QLineEdit:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        line = QLineEdit(default)
        row_layout.addWidget(line, stretch=1)
        button = QPushButton("Pick")
        button.setFixedWidth(56)
        button.clicked.connect(lambda: self.choose_color(line))
        row_layout.addWidget(button)
        form.addRow(label, row)
        return line

    def _setup_shortcuts(self) -> None:
        action_open = QAction(self)
        action_open.setShortcut(QKeySequence.StandardKey.Open)
        action_open.triggered.connect(self.pick_image)
        self.addAction(action_open)

        action_preview = QAction(self)
        action_preview.setShortcut(QKeySequence("Ctrl+R"))
        action_preview.triggered.connect(self.render_preview)
        self.addAction(action_preview)

        action_export = QAction(self)
        action_export.setShortcut(QKeySequence("Ctrl+E"))
        action_export.triggered.connect(self.export_rendered)
        self.addAction(action_export)

        action_save_template = QAction(self)
        action_save_template.setShortcut(QKeySequence("Ctrl+S"))
        action_save_template.triggered.connect(self.save_template)
        self.addAction(action_save_template)

    def _apply_system_adaptive_style(self) -> None:
        palette = self.palette()
        window_color = palette.color(QPalette.ColorRole.Window)
        base_color = palette.color(QPalette.ColorRole.Base)
        text_color = palette.color(QPalette.ColorRole.Text)
        button_color = palette.color(QPalette.ColorRole.Button)
        button_text = palette.color(QPalette.ColorRole.ButtonText)
        disabled_text = palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)

        dark_mode = window_color.lightness() < 128
        border_color = window_color.lighter(135) if dark_mode else window_color.darker(130)
        input_border = border_color
        button_border = border_color
        button_hover = button_color.lighter(115) if dark_mode else button_color.darker(104)
        preview_bg = window_color.lighter(110) if dark_mode else window_color.darker(103)
        preview_text = text_color.lighter(135) if dark_mode else text_color.darker(130)

        self.setStyleSheet(
            f"""
            QWidget {{
                font-size: 13px;
            }}
            QLabel {{
                color: {text_color.name()};
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
                color: {text_color.name()};
                font-weight: 600;
            }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {{
                border: 1px solid {input_border.name()};
                border-radius: 7px;
                padding: 4px 6px;
                background: {base_color.name()};
                color: {text_color.name()};
            }}
            QPushButton {{
                border: 1px solid {button_border.name()};
                border-radius: 7px;
                background: {button_color.name()};
                color: {button_text.name()};
                padding: 6px 10px;
            }}
            QPushButton:hover {{
                background: {button_hover.name()};
            }}
            QPushButton:disabled {{
                color: {disabled_text.name()};
            }}
            QLabel#PreviewLabel {{
                border: 1px solid {border_color.name()};
                border-radius: 10px;
                background: {preview_bg.name()};
                color: {preview_text.name()};
            }}
            """
        )

    def _set_status(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def _show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _collect_show_fields(self) -> set[str]:
        return {name for name, check in self.show_field_checks.items() if check.isChecked()}

    def _build_template(self) -> RenderTemplate:
        payload = {
            "name": self.template_name_input.text().strip() or "custom",
            "banner_height": self.banner_height_spin.value(),
            "left_ratio": self.left_ratio_spin.value(),
            "padding": {"x": self.padding_x_spin.value(), "y": self.padding_y_spin.value()},
            "colors": {
                "background": _safe_color(self.color_inputs["background"].text(), "#F2F2F2"),
                "text": _safe_color(self.color_inputs["text"].text(), "#111111"),
                "muted": _safe_color(self.color_inputs["muted"].text(), "#4A4A4A"),
                "divider": _safe_color(self.color_inputs["divider"].text(), "#D0D0D0"),
            },
            "fonts": {
                "title": self.title_font_spin.value(),
                "body": self.body_font_spin.value(),
                "small": self.small_font_spin.value(),
            },
            "divider": self.divider_check.isChecked(),
            "logo": self.logo_input.text().strip() or None,
        }
        return normalize_template_dict(payload)

    def _build_render_options(self) -> RenderOptions:
        return RenderOptions(
            show_fields=self._collect_show_fields(),
            show_eq_focal=self.show_eq_focal_check.isChecked(),
            fallback_text="N/A",
        )

    def _build_metadata(self) -> NormalizedMetadata:
        if not self.image_path:
            raise RuntimeError("No image loaded")
        bird_override = self.bird_override_input.text().strip() or None
        return normalize_metadata(
            self.image_path,
            self.raw_metadata,
            bird_arg=bird_override,
            bird_priority=["arg", "meta", "filename"],
            bird_regex=DEFAULT_BIRD_REGEX,
            time_format="%Y-%m-%d %H:%M",
        )

    def _apply_template_to_controls(self, template: RenderTemplate) -> None:
        self.template_name_input.setText(template.name)
        self.banner_height_spin.setValue(template.banner_height)
        self.left_ratio_spin.setValue(template.left_ratio)
        self.padding_x_spin.setValue(template.padding_x)
        self.padding_y_spin.setValue(template.padding_y)
        self.title_font_spin.setValue(template.fonts["title"])
        self.body_font_spin.setValue(template.fonts["body"])
        self.small_font_spin.setValue(template.fonts["small"])
        self.divider_check.setChecked(template.divider)
        self.logo_input.setText(template.logo or "")
        self.color_inputs["background"].setText(template.colors.get("background", "#F2F2F2"))
        self.color_inputs["text"].setText(template.colors.get("text", "#111111"))
        self.color_inputs["muted"].setText(template.colors.get("muted", "#4A4A4A"))
        self.color_inputs["divider"].setText(template.colors.get("divider", "#D0D0D0"))

    def _load_template_by_name(self, name: str) -> None:
        if not name:
            return
        try:
            template = load_template(name)
        except Exception as exc:
            self._show_error("Template Error", str(exc))
            self._set_status(f"Template load failed: {exc}")
            return
        self._apply_template_to_controls(template)
        self._set_status(f"Loaded template: {name}")
        if self.base_image:
            self.render_preview()

    def _build_metadata_summary(self) -> str:
        if not self.image_path:
            return "Open an image to start."
        try:
            metadata = self._build_metadata()
        except Exception:
            return "Metadata parse failed."
        lines = [
            f"Bird: {metadata.bird or 'N/A'}",
            f"Time: {metadata.capture_text or 'N/A'}",
            f"Location: {metadata.location or metadata.gps_text or 'N/A'}",
            f"Camera: {metadata.camera or 'N/A'}",
            f"Lens: {metadata.lens or 'N/A'}",
        ]
        return "\n".join(lines)

    def _refresh_preview_label(self) -> None:
        if not self.preview_pixmap:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("Open an image to preview.")
            return
        target = self.preview_label.size()
        scaled = self.preview_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)
        self.preview_label.setText("")

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._refresh_preview_label()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange}:
            self._apply_system_adaptive_style()
        super().changeEvent(event)

    def pick_image(self) -> None:
        ext_pattern = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open image",
            "",
            f"Supported Images ({ext_pattern});;All Files (*.*)",
        )
        if not file_path:
            return
        self.open_image(Path(file_path))

    def open_image(self, path: Path) -> None:
        try:
            decoded = decode_image(path, decoder="auto")
        except Exception as exc:
            self._show_error("Image Error", str(exc))
            self._set_status(f"Failed to open image: {exc}")
            return

        resolved = path.resolve(strict=False)
        try:
            raw_map = extract_many([resolved], mode="auto")
            raw_metadata = raw_map.get(resolved) or extract_pillow_metadata(path)
            meta_state = "ok"
        except Exception as exc:
            raw_metadata = {"SourceFile": str(path)}
            meta_state = f"fallback ({exc})"

        self.base_image = decoded
        self.image_path = path
        self.raw_metadata = raw_metadata
        self.path_edit.setText(str(path))
        self.meta_text.setPlainText(self._build_metadata_summary())
        if meta_state == "ok":
            self._set_status(f"Opened image: {path.name}")
        else:
            self._set_status(f"Opened image with limited metadata: {path.name}")
        self.render_preview()

    def render_preview(self) -> None:
        if not self.base_image or not self.image_path:
            self._set_status("Open an image first.")
            return

        try:
            template = self._build_template()
            metadata = self._build_metadata()
            options = self._build_render_options()
            processed = apply_output_mode(
                self.base_image.copy(),
                mode=self.mode_combo.currentText().lower(),
                max_long_edge=self.max_long_edge_spin.value(),
                frame_style=self.frame_style_combo.currentText().lower(),
                fill_color=template.colors.get("background", "#FFFFFF"),
            )
            rendered = render_banner(processed, metadata, template, options)
            self.last_rendered = rendered
            self.preview_pixmap = _pil_to_qpixmap(rendered)
            self._refresh_preview_label()
            self._set_status(f"Preview updated: {rendered.width}x{rendered.height}")
        except Exception as exc:
            self._show_error("Render Error", str(exc))
            self._set_status(f"Preview failed: {exc}")

    def choose_color(self, target_input: QLineEdit) -> None:
        initial = QColor(target_input.text().strip() or "#ffffff")
        chosen = QColorDialog.getColor(initial, self, "Pick color")
        if not chosen.isValid():
            return
        target_input.setText(chosen.name())
        if self.base_image:
            self.render_preview()

    def apply_theme_colors(self) -> None:
        theme = self.theme_combo.currentText().strip().lower()
        overrides = THEME_OVERRIDES.get(theme)
        if not overrides:
            QMessageBox.warning(self, "Theme", f"Unknown theme: {theme}")
            return
        self.color_inputs["background"].setText(overrides["background"])
        self.color_inputs["text"].setText(overrides["text"])
        self.color_inputs["muted"].setText(overrides["muted"])
        self.color_inputs["divider"].setText(overrides["divider"])
        self._set_status(f"Applied theme colors: {theme}")
        if self.base_image:
            self.render_preview()

    def load_template_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load template file",
            "",
            "Template Files (*.yaml *.yml *.json);;All Files (*.*)",
        )
        if not file_path:
            return
        path = Path(file_path)
        try:
            template = load_template(str(path))
        except Exception as exc:
            self._show_error("Template Error", str(exc))
            self._set_status(f"Template load failed: {exc}")
            return
        self._apply_template_to_controls(template)
        self._set_status(f"Loaded template file: {path.name}")
        if self.base_image:
            self.render_preview()

    def _template_payload(self) -> dict[str, Any]:
        template = self._build_template()
        return {
            "name": template.name,
            "banner_height": template.banner_height,
            "left_ratio": template.left_ratio,
            "padding": {"x": template.padding_x, "y": template.padding_y},
            "colors": {
                "background": template.colors.get("background", "#F2F2F2"),
                "text": template.colors.get("text", "#111111"),
                "muted": template.colors.get("muted", "#4A4A4A"),
                "divider": template.colors.get("divider", "#D0D0D0"),
            },
            "fonts": {
                "title": template.fonts.get("title", 56),
                "body": template.fonts.get("body", 32),
                "small": template.fonts.get("small", 22),
            },
            "divider": template.divider,
            "logo": template.logo,
        }

    def save_template(self) -> None:
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save template",
            "template.yaml",
            "YAML (*.yaml *.yml);;JSON (*.json);;All Files (*.*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        payload = self._template_payload()
        try:
            if path.suffix.lower() == ".json":
                path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                if path.suffix.lower() not in {".yaml", ".yml"}:
                    path = path.with_suffix(".yaml")
                path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        except Exception as exc:
            self._show_error("Save Error", str(exc))
            self._set_status(f"Template save failed: {exc}")
            return
        self._set_status(f"Template saved: {path}")

    def export_rendered(self) -> None:
        if self.last_rendered is None:
            self.render_preview()
        if self.last_rendered is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export rendered image",
            "rendered.jpg",
            "JPEG (*.jpg *.jpeg);;PNG (*.png);;All Files (*.*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            path = path.with_suffix(".jpg")
            suffix = ".jpg"

        try:
            if suffix == ".png":
                self.last_rendered.save(path, format="PNG", optimize=True)
            else:
                self.last_rendered.save(path, format="JPEG", quality=92, optimize=True, progressive=True)
        except Exception as exc:
            self._show_error("Export Error", str(exc))
            self._set_status(f"Export failed: {exc}")
            return
        self._set_status(f"Exported: {path}")


def launch_gui(startup_file: Path | None = None) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    window = BirdStampEditorWindow(startup_file=startup_file)
    window.show()
    app.exec()
