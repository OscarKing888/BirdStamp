from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

from birdstamp.models import RenderTemplate

THEME_OVERRIDES: dict[str, dict[str, str]] = {
    "light": {
        "background": "#FFFFFF",
        "text": "#333333",
        "muted": "#5F5F5F",
        "divider": "#D8D8D8",
    },
    "gray": {
        "background": "#ECECEC",
        "text": "#333333",
        "muted": "#5A5A5A",
        "divider": "#C8C8C8",
    },
    "dark": {
        "background": "#121212",
        "text": "#F0F0F0",
        "muted": "#B0B0B0",
        "divider": "#3A3A3A",
    },
}


def list_builtin_templates() -> list[str]:
    files = resources.files("birdstamp.templates")
    names = []
    for item in files.iterdir():
        if item.name.endswith((".yaml", ".yml", ".json")):
            names.append(Path(item.name).stem)
    return sorted(set(names))


def _load_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"template file is not a dict: {path}")
    return data


def _load_builtin(name: str) -> dict[str, Any]:
    pkg = resources.files("birdstamp.templates")
    for suffix in (".yaml", ".yml", ".json"):
        candidate = pkg / f"{name}{suffix}"
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
            if suffix == ".json":
                data = json.loads(text)
            else:
                data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
    raise FileNotFoundError(f"built-in template not found: {name}")


def normalize_template_dict(data: dict[str, Any]) -> RenderTemplate:
    colors = {
        "background": "#ECECEC",
        "text": "#333333",
        "muted": "#5A5A5A",
        "divider": "#C8C8C8",
    }
    colors.update(data.get("colors") or {})

    fonts = {"title": 72, "body": 40, "small": 28}
    fonts.update(data.get("fonts") or {})

    padding = {"x": 48, "y": 24}
    padding.update(data.get("padding") or {})

    name = str(data.get("name") or "custom")
    banner_height = int(data.get("banner_height") or 260)
    left_ratio = float(data.get("left_ratio") or 0.58)
    divider = bool(data.get("divider", True))
    logo = data.get("logo")
    logo = str(logo) if logo else None

    return RenderTemplate(
        name=name,
        banner_height=max(80, banner_height),
        left_ratio=min(0.8, max(0.3, left_ratio)),
        padding_x=max(8, int(padding["x"])),
        padding_y=max(8, int(padding["y"])),
        colors=colors,
        fonts={
            "title": max(10, int(fonts["title"])),
            "body": max(10, int(fonts["body"])),
            "small": max(8, int(fonts["small"])),
        },
        divider=divider,
        logo=logo,
    )


def _normalize_template(data: dict[str, Any]) -> RenderTemplate:
    return normalize_template_dict(data)


def load_template(
    template_name_or_path: str,
    theme: str | None = None,
    banner_height: int | None = None,
) -> RenderTemplate:
    path = Path(template_name_or_path)
    if path.exists():
        raw = _load_file(path)
    else:
        raw = _load_builtin(template_name_or_path)

    tpl = _normalize_template(raw)
    if theme:
        theme = theme.lower()
        if theme in THEME_OVERRIDES:
            tpl.colors.update(THEME_OVERRIDES[theme])
    if banner_height:
        tpl.banner_height = max(80, int(banner_height))
    return tpl
