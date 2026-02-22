# 极速鸟框

`birdstamp` is a cross-platform Python tool for batch rendering bird-photo outputs with a metadata banner.

## Features

- Batch process single files or directories (`--recursive`).
- Decode JPG/JPEG/PNG/TIFF, optional HEIF/HEIC/HIF, optional RAW.
- Metadata extraction:
  - Preferred: ExifTool (`auto|on|off`)
  - Fallback: Pillow EXIF
- Render banner templates (YAML/JSON), built-in: `default/minimal/dark/compact`.
- Bird name priority: CLI arg, metadata, filename regex.
- Output modes: `keep`, `fit`, `square`, `vertical`.
- Commands:
  - `birdstamp render`
  - `birdstamp inspect`
  - `birdstamp templates`
  - `birdstamp init-config`
  - `birdstamp gui`

## Install

```bash
pip install .
```

Optional extras:

```bash
pip install .[raw,heif,gui]
```

- `raw`: enables `rawpy` decoding.
- `heif`: enables `pillow-heif` decoding.
- `gui`: enables PyQt6 GUI editor.

## Quick Start

```bash
birdstamp render ./photos --recursive --out ./output --template default --theme gray --bird "灰喜鹊"
```

Print parsed metadata:

```bash
birdstamp inspect ./photos/IMG_0001.JPG
```

Initialize user config:

```bash
birdstamp init-config
```

Open GUI editor:

```bash
birdstamp gui
```

Open GUI with a startup image:

```bash
birdstamp gui --file ./photos/IMG_0001.JPG
```

GUI capabilities:

- Open an image and preview rendered output.
- Edit template layout, fonts, colors, divider, and logo.
- Toggle shown fields and output mode.
- Save current template as YAML/JSON.
- Export rendered image as JPEG/PNG.

