#!/bin/bash
# Comic Viewer インストールスクリプト
# このスクリプトをコミックビューアフォルダの中から実行してください

set -e

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$HOME/.local/lib/comic_viewer"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"

echo "インストール先: $INSTALL_DIR"

mkdir -p "$INSTALL_DIR" "$DESKTOP_DIR" "$ICON_DIR"
cp -r "$SRC/_internal" "$INSTALL_DIR/"
cp "$SRC/comic_viewer"  "$INSTALL_DIR/"
cp "$SRC/icon.png"      "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/comic_viewer"

cp "$SRC/icon.png" "$ICON_DIR/comic_viewer.png"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

cat > "$DESKTOP_DIR/comic_viewer.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=Comic Viewer
Comment=コミック・画像ビューア
Exec=$INSTALL_DIR/comic_viewer
Icon=comic_viewer
Terminal=false
Categories=Graphics;Viewer;
StartupWMClass=comic_viewer
DESKTOP

chmod +x "$DESKTOP_DIR/comic_viewer.desktop"

echo "✓ インストール完了"
echo "  アプリメニューまたはデスクトップから「Comic Viewer」を起動できます。"
echo "  ZIPを解凍したフォルダは削除してかまいません。"
echo ""
echo "  アンインストールするには:"
echo "    bash uninstall.sh"
