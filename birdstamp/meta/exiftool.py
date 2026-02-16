from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Iterable

from birdstamp.subprocess_utils import decode_subprocess_output

LOGGER = logging.getLogger(__name__)
EXIFTOOL_BIN = os.environ.get("EXIFTOOL_BIN", "exiftool")


def is_exiftool_available() -> bool:
    try:
        result = subprocess.run(
            [EXIFTOOL_BIN, "-ver"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return False
    return result.returncode == 0


def _chunked(items: list[Path], size: int) -> Iterable[list[Path]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def extract_many(paths: list[Path], mode: str = "auto", chunk_size: int = 128) -> dict[Path, dict[str, Any]]:
    mode = mode.lower()
    if mode == "off" or not paths:
        return {}
    if mode not in {"auto", "on", "off"}:
        raise ValueError(f"invalid use-exiftool mode: {mode}")

    available = is_exiftool_available()
    if not available:
        if mode == "on":
            raise RuntimeError("ExifTool is required but not found in PATH")
        LOGGER.debug("ExifTool not found, fallback metadata readers will be used")
        return {}

    all_results: dict[Path, dict[str, Any]] = {}
    for chunk in _chunked(paths, chunk_size):
        cmd = [
            EXIFTOOL_BIN,
            "-j",
            "-n",
            "-a",
            "-u",
            "-api",
            "largefilesupport=1",
            *[str(p) for p in chunk],
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, check=False)
        except FileNotFoundError:
            if mode == "on":
                raise RuntimeError("ExifTool is required but not found in PATH")
            LOGGER.debug("ExifTool not found while extracting metadata")
            return all_results

        stdout_text = decode_subprocess_output(result.stdout)
        stderr_text = decode_subprocess_output(result.stderr).strip()
        if result.returncode != 0:
            message = stderr_text or "unknown error"
            if mode == "on":
                raise RuntimeError(f"ExifTool extraction failed: {message}")
            LOGGER.warning("ExifTool extraction failed for a chunk: %s", message)
            continue
        try:
            payload = json.loads(stdout_text)
        except json.JSONDecodeError:
            if mode == "on":
                raise RuntimeError("ExifTool returned invalid JSON")
            LOGGER.warning("ExifTool returned invalid JSON, skipping chunk")
            continue
        if not isinstance(payload, list):
            continue
        for item in payload:
            if not isinstance(item, dict):
                continue
            source_file = item.get("SourceFile")
            if not source_file:
                continue
            source_path = Path(str(source_file)).resolve(strict=False)
            all_results[source_path] = item

    return all_results
