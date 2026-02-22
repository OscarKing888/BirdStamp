#!/usr/bin/env bash
# test_render.sh — BirdStamp CLI 渲染回归测试
#
# 用法：
#   bash scripts_dev/test_render.sh
#
# 流程：
#   1. 以 images/default.jpg 为输入
#   2. 使用 config/templates/default.json 模板（若不存在则用内置默认）
#   3. 输出到 output/ 目录
#   4. 验证输出文件存在且大小合理
# ---------------------------------------------------------------------------

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── resolve Python ────────────────────────────────────────────────────────────
PYTHON="python3"
if [[ -f ".venv/bin/python3" ]]; then PYTHON=".venv/bin/python3"; fi

# ── paths ─────────────────────────────────────────────────────────────────────
INPUT="images/default.jpg"
OUT_DIR="output"
TEMPLATE="default"

if [[ ! -f "$INPUT" ]]; then
    echo "ERROR: 输入文件不存在: $INPUT" >&2
    exit 1
fi

# ── clean previous output ─────────────────────────────────────────────────────
if [[ -d "$OUT_DIR" ]]; then
    echo "清理旧输出目录: $OUT_DIR"
    rm -rf "$OUT_DIR"
fi

echo "============================================================"
echo " BirdStamp CLI 渲染回归测试"
echo "   输入   : $INPUT"
echo "   模板   : $TEMPLATE"
echo "   输出   : $OUT_DIR/"
echo "============================================================"

# ── run render ────────────────────────────────────────────────────────────────
"$PYTHON" -m birdstamp render "$INPUT" \
    --out "$OUT_DIR" \
    --template "$TEMPLATE" \
    --no-skip-existing \
    --log-level info

# ── verify output ─────────────────────────────────────────────────────────────
OUTPUT_FILES=("$OUT_DIR"/*.jpg "$OUT_DIR"/*.jpeg "$OUT_DIR"/*.png)
FOUND=0
for f in "${OUTPUT_FILES[@]}"; do
    [[ -f "$f" ]] && FOUND=$((FOUND + 1))
done

if [[ $FOUND -eq 0 ]]; then
    echo ""
    echo "FAIL: output/ 目录中未找到输出图像" >&2
    exit 1
fi

# 验证第一个输出文件大小 > 10KB
FIRST_OUTPUT=""
for f in "${OUTPUT_FILES[@]}"; do
    [[ -f "$f" ]] && FIRST_OUTPUT="$f" && break
done

FILE_SIZE=$(stat -f%z "$FIRST_OUTPUT" 2>/dev/null || stat -c%s "$FIRST_OUTPUT" 2>/dev/null || echo 0)
if [[ $FILE_SIZE -lt 10240 ]]; then
    echo ""
    echo "FAIL: 输出文件过小 (${FILE_SIZE} bytes)，可能渲染异常: $FIRST_OUTPUT" >&2
    exit 1
fi

echo ""
echo "============================================================"
echo " PASS  共生成 ${FOUND} 个文件"
echo "   输出文件: $FIRST_OUTPUT (${FILE_SIZE} bytes)"
echo "============================================================"
