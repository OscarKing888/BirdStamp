from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

LOGGER = logging.getLogger(__name__)


def _ratio_to_float(value: Any) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        if denominator == 0:
            return 0.0
        return float(numerator) / float(denominator)
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if numerator is not None and denominator not in (None, 0):
        return float(numerator) / float(denominator)
    return float(value)


def _dms_to_degree(values: Any, ref: str | None) -> float | None:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        return None
    try:
        d = _ratio_to_float(values[0])
        m = _ratio_to_float(values[1])
        s = _ratio_to_float(values[2])
    except Exception:
        return None
    degree = d + (m / 60.0) + (s / 3600.0)
    if ref and ref.upper() in {"S", "W"}:
        degree = -degree
    return degree


def extract_pillow_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {"SourceFile": str(path)}
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            if not exif:
                return metadata

            for tag_id, value in exif.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if tag != "GPSInfo":
                    metadata[tag] = value
                    continue
                if not isinstance(value, dict):
                    continue
                gps_info = {ExifTags.GPSTAGS.get(k, str(k)): v for k, v in value.items()}
                metadata["GPSInfo"] = gps_info
                lat = _dms_to_degree(gps_info.get("GPSLatitude"), gps_info.get("GPSLatitudeRef"))
                lon = _dms_to_degree(gps_info.get("GPSLongitude"), gps_info.get("GPSLongitudeRef"))
                if lat is not None:
                    metadata["GPSLatitude"] = lat
                if lon is not None:
                    metadata["GPSLongitude"] = lon
    except Exception as exc:
        LOGGER.debug("Pillow metadata fallback failed for %s: %s", path, exc)
    return metadata
