#!/usr/bin/env bash
set -euo pipefail

# 分步打包 macOS .app，避免一次性复制 500+ MB 后端资源超时
# 用法: ./build-macos-bundle.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIST="$SCRIPT_DIR/../packaging/dist/daxi"
TAURI_DIR="$SCRIPT_DIR/src-tauri"
RELEASE_DIR="$TAURI_DIR/target/release"
BUNDLE_DIR="$RELEASE_DIR/bundle/macos"
APP_NAME="daxi.app"
APP_PATH="$BUNDLE_DIR/$APP_NAME"
BINARY_NAME="daxi-desktop"  # 从 tauri.conf.json productName 来

echo "=== 第 1 步: 检查后端 dist 是否已精简 ==="
if [[ -d "$BACKEND_DIST/ms-playwright/chromium_headless_shell-1228" ]]; then
    echo "❌ 发现未删除的 chromium_headless_shell (192MB)"
    echo "   请先运行: rm -rf $BACKEND_DIST/ms-playwright/chromium_headless_shell-1228"
    exit 1
fi
BACKEND_SIZE=$(du -sh "$BACKEND_DIST" | cut -f1)
echo "✅ 后端包大小: $BACKEND_SIZE"

echo ""
echo "=== 第 2 步: 清理旧 bundle ==="
rm -rf "$BUNDLE_DIR"

echo ""
echo "=== 第 3 步: 构建前端 ==="
cd "$SCRIPT_DIR"
npm run build

echo ""
echo "=== 第 4 步: 构建 Tauri 壳 (不带资源) ==="
# 暂时移走 resources 配置，只 build 壳
CONF_FILE="$TAURI_DIR/tauri.conf.json"
CONF_BACKUP="$TAURI_DIR/tauri.conf.json.bak"
cp "$CONF_FILE" "$CONF_BACKUP"

# 用 jq 删掉 bundle.resources (如果没装 jq 就用 sed)
if command -v jq &>/dev/null; then
    jq 'del(.bundle.resources)' "$CONF_BACKUP" > "$CONF_FILE"
else
    # sed 简单粗暴:删掉包含 "resources" 的三行
    sed '/"resources"/,+2d' "$CONF_BACKUP" > "$CONF_FILE"
fi

npm run tauri build -- --no-bundle
cp "$CONF_BACKUP" "$CONF_FILE"

echo ""
echo "=== 第 5 步: 手动创建 .app bundle 结构 ==="
mkdir -p "$BUNDLE_DIR"
CONTENTS="$APP_PATH/Contents"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

# 复制可执行文件和 Info.plist
cp "$RELEASE_DIR/$BINARY_NAME" "$CONTENTS/MacOS/"
cp "$TAURI_DIR/Info.plist" "$CONTENTS/" 2>/dev/null || echo "⚠️  未找到 Info.plist (可选)"

# 复制前端资源 (图标等)
if [[ -d "$TAURI_DIR/icons" ]]; then
    cp -r "$TAURI_DIR/icons" "$CONTENTS/Resources/"
fi

echo ""
echo "=== 第 6 步: 分块复制后端到 Resources/backend (避免超时) ==="
DEST_BACKEND="$CONTENTS/Resources/backend"
mkdir -p "$DEST_BACKEND"

# 先复制小文件 (快速)
echo "  → 复制主可执行文件和小文件..."
rsync -a --exclude='ms-playwright' "$BACKEND_DIST/" "$DEST_BACKEND/"

# 再复制 Chromium (慢，显示进度)
echo "  → 复制 Chromium (344MB，需要 1-2 分钟)..."
mkdir -p "$DEST_BACKEND/ms-playwright"
rsync -a --info=progress2 "$BACKEND_DIST/ms-playwright/" "$DEST_BACKEND/ms-playwright/"

echo ""
echo "=== 第 7 步: 设置权限 ==="
chmod +x "$CONTENTS/MacOS/$BINARY_NAME"
chmod +x "$DEST_BACKEND/daxi" 2>/dev/null || true

echo ""
echo "=== 第 8 步: 验证 bundle ==="
FINAL_SIZE=$(du -sh "$APP_PATH" | cut -f1)
echo "✅ .app 大小: $FINAL_SIZE"
echo "✅ 产物路径: $APP_PATH"

echo ""
echo "=== 完成! ==="
echo "运行: open $APP_PATH"
