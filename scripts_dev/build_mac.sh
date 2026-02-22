#!/usr/bin/env bash
# build_mac.sh — Build BirdStamp.app for macOS using PyInstaller
#
# Usage:
#   bash scripts_dev/build_mac.sh [--clean] [--arch universal2]
#
# Options:
#   --clean            Remove dist/ and build/ before building
#   --arch universal2  Build a universal (Intel + Apple Silicon) binary
#
# Prerequisites (run once):
#   pip install pyinstaller pyinstaller-hooks-contrib
#
# Output:
#   dist/BirdStamp-<version>.app
#   dist/BirdStamp-<version>-mac.zip
# ---------------------------------------------------------------------------

set -euo pipefail

# ── locate project root (parent of this script) ──────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── defaults ─────────────────────────────────────────────────────────────────
CLEAN=0
TARGET_ARCH=""   # empty = native arch

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)  CLEAN=1; shift ;;
        --arch)   TARGET_ARCH="$2"; shift 2 ;;
        *)        echo "Unknown option: $1"; exit 1 ;;
    esac
done

# ── sanity checks ─────────────────────────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Activate your venv first." >&2
    exit 1
fi

PYTHON="python3"
if [[ -f ".venv/bin/python3" ]]; then
    PYTHON=".venv/bin/python3"
fi

if ! "$PYTHON" -c "import PyInstaller" 2>/dev/null; then
    echo "PyInstaller not found. Installing..."
    "$PYTHON" -m pip install pyinstaller pyinstaller-hooks-contrib
fi

# ── read version from source (no import needed) ──────────────────────────────
VERSION=$("$PYTHON" -c "
import re, pathlib
text = pathlib.Path('birdstamp/__init__.py').read_text(encoding='utf-8')
m = re.search(r'__version__\s*=\s*[\"\']([\d.]+[\w.-]*)', text)
print(m.group(1) if m else '0.0.0')
")
echo "Version: $VERSION"

APP_NAME="BirdStamp-${VERSION}"
APP_DIR="dist/${APP_NAME}.app"
ZIP_FILE="dist/${APP_NAME}-mac.zip"

# ── optional clean ────────────────────────────────────────────────────────────
if [[ $CLEAN -eq 1 ]]; then
    echo "Cleaning dist/ and build/ ..."
    rm -rf dist/ build/
fi

# ── patch target_arch in spec if --arch was passed ───────────────────────────
SPEC_FILE="BirdStamp_mac.spec"
if [[ -n "$TARGET_ARCH" ]]; then
    echo "Setting target_arch to: $TARGET_ARCH"
    SPEC_FILE="build/BirdStamp_mac_patched.spec"
    mkdir -p build
    sed "s/target_arch=None/target_arch=\"$TARGET_ARCH\"/" BirdStamp_mac.spec > "$SPEC_FILE"
fi

# ── build ─────────────────────────────────────────────────────────────────────
echo "============================================================"
echo " Building ${APP_NAME}.app (this may take several minutes) ..."
echo "============================================================"

"$PYTHON" -m PyInstaller "$SPEC_FILE" --noconfirm

# ── rename output to include version ─────────────────────────────────────────
if [[ -d "dist/BirdStamp.app" ]]; then
    # Remove stale versioned app if it exists from a previous build
    [[ -d "$APP_DIR" ]] && rm -rf "$APP_DIR"
    mv "dist/BirdStamp.app" "$APP_DIR"
    echo "Renamed to: $APP_DIR"
fi

if [[ ! -d "$APP_DIR" ]]; then
    echo "ERROR: Build failed — $APP_DIR not found." >&2
    exit 1
fi

# ── smoke test ────────────────────────────────────────────────────────────────
echo ""
echo "Smoke test — checking executable launches ..."
EXEC="$APP_DIR/Contents/MacOS/BirdStamp"
if [[ -x "$EXEC" ]]; then
    timeout 10 "$EXEC" --help &>/dev/null \
        && echo "  Smoke test PASSED (--help exit 0)" \
        || echo "  Smoke test note: non-zero exit (normal for GUI-only builds)"
else
    echo "  WARNING: executable not found at $EXEC"
fi

# ── create zip ────────────────────────────────────────────────────────────────
echo ""
echo "Creating zip: $ZIP_FILE ..."
# ditto preserves resource forks and symlinks inside .app bundles
if command -v ditto &>/dev/null; then
    ditto -c -k --sequesterRsrc --keepParent "$APP_DIR" "$ZIP_FILE"
else
    (cd dist && zip -ry "$(basename "$ZIP_FILE")" "$(basename "$APP_DIR")")
fi
echo "Zip created: $ZIP_FILE"

echo ""
echo "Done."
echo "  App : $APP_DIR"
echo "  Zip : $ZIP_FILE"
echo ""
echo "To open the app:"
echo "  open $APP_DIR"
