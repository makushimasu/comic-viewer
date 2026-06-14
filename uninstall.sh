#!/bin/bash
# Comic Viewer アンインストールスクリプト

INSTALL_DIR="$HOME/.local/lib/comic_viewer"
DESKTOP_FILE="$HOME/.local/share/applications/comic_viewer.desktop"
ICON_FILE="$HOME/.local/share/icons/hicolor/256x256/apps/comic_viewer.png"
DATA_DIR="$HOME/comic_viewer"

echo "Comic Viewer をアンインストールします。"
echo ""

if [ -d "$DATA_DIR" ]; then
    echo "本棚の登録データ・読書進捗・キャッシュも削除しますか？"
    echo "  削除する場合: これまでの本棚登録・しおり・読んだページ数がすべて消えます"
    echo "  削除しない場合: 再インストール後にそのまま引き継げます"
    echo ""
    read -p "データも削除しますか？ [y/N]: " answer
    case "$answer" in
        [yY]) DELETE_DATA=true ;;
        *)    DELETE_DATA=false ;;
    esac
fi

rm -rf "$INSTALL_DIR"
rm -f "$DESKTOP_FILE"
rm -f "$ICON_FILE"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

if [ "$DELETE_DATA" = true ]; then
    rm -rf "$DATA_DIR"
    echo "✓ アプリデータも削除しました"
fi

echo "✓ アンインストール完了"
