# main.py
import sys
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QListView, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QWidget, QLabel, QMessageBox, QToolBar, QMenu,
    QFileDialog, QPushButton, QSizePolicy as SP, QStyledItemDelegate,
    QStyle, QLineEdit
)
from PySide6.QtGui import (
    QStandardItemModel, QStandardItem, QIcon, QPixmap, QFont,
    QAction, QImage, QPainter, QTextOption, QLinearGradient, QColor, QBrush,
    QCursor
)
from PySide6.QtCore import Qt, QSize, QThread, Signal, QObject, QTimer, QRect, QPoint

from core import create_thumbnail, get_cache_path, is_placeholder_cache
from utils import parse_filename
from viewer import ViewerWindow
from settings import load_settings, SettingsDialog
from i18n import tr

from appdir import APP_DIR

LIBRARY_DB         = APP_DIR / "library.json"
LAST_LOC_FILE      = APP_DIR / "last_location.json"
HISTORY_FILE       = APP_DIR / "history.json"
SHELF_LAYOUT_FILE  = APP_DIR / "shelf_layout.json"  # 手動配置の保存先

HISTORY_MAX = 30  # 閲覧履歴の最大保持件数


def _has_rar_support() -> bool:
    """RAR展開手段が1つでも使えるか確認（libarchive / 7z / unrar）"""
    import sys
    import shutil
    from archive import _lib
    if _lib is not None:
        return True
    if sys.platform == "win32":
        for cmd in ("7z", "7za", "7zz", "unrar"):
            if shutil.which(cmd):
                return True
        return any(
            Path(p).exists() for p in (
                r"C:\Program Files\7-Zip\7z.exe",
                r"C:\Program Files (x86)\7-Zip\7z.exe",
            )
        )
    return any(shutil.which(cmd) for cmd in ("unar", "unrar"))


def _info_msg(parent, title: str, text: str):
    """スタイルを明示したインフォメーションダイアログ（親のスタイル継承を防ぐ）"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(title)
    msg.setIcon(QMessageBox.Information)
    msg.setText(text)
    msg.setStyleSheet("""
        QMessageBox { background: #faf5ee; }
        QLabel { color: #1a0800; font-size: 11pt; }
        QPushButton {
            background: #5a8a3c; color: white;
            border-radius: 6px; padding: 6px 18px;
        }
        QPushButton:hover { background: #4a7a2c; }
    """)
    msg.exec()


def _show_unrar_notice(parent=None):
    """unrarがない場合にインストールを促すメッセージを表示"""
    msg = QMessageBox(parent)
    msg.setWindowTitle(tr("rar_title"))
    msg.setIcon(QMessageBox.Information)
    msg.setText(tr("rar_text"))
    import sys as _sys
    info_key = "rar_info" if _sys.platform == "win32" else "rar_info_linux"
    msg.setInformativeText(tr(info_key))
    msg.setStyleSheet("""
        QMessageBox { background: #faf5ee; }
        QLabel { color: #1a0800; font-size: 11pt; }
        QPushButton {
            background: #5a8a3c; color: white;
            border-radius: 6px; padding: 6px 18px;
        }
        QPushButton:hover { background: #4a7a2c; }
    """)
    msg.exec()

# デリゲートが参照する表示名ロール（Qt.DisplayRoleは空にしてデフォルト描画を抑制）
TITLE_ROLE   = Qt.UserRole + 1
IS_DIR_ROLE  = Qt.UserRole + 2  # フォルダかどうか（ワーカーが設定）
PIXMAP_ROLE  = Qt.UserRole + 3  # QPixmapを直接保存（QIconを経由しない）
CACHED_ROLE   = Qt.UserRole + 4  # ページキャッシュ済みかどうか
PROGRESS_ROLE = Qt.UserRole + 5  # しおり状態: None=未読, 'reading'=途中, 'done'=読了
SERIES_ROLE   = Qt.UserRole + 6  # シリーズグループの構成ファイルパスリスト（代表アイテムのみ）
PLACEHOLDER_ROLE = Qt.UserRole + 7  # 手動配置モードの空き段を表すプレースホルダー行

# 本棚に表示する対応拡張子
SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",
    ".zip", ".rar", ".cbz", ".cbr", ".7z", ".cb7",
}

# PDFはpypdfium2がある場合のみ対応（無い環境では一覧に表示しない）
try:
    from archive import has_pdf_support as _has_pdf_support
    if _has_pdf_support():
        SUPPORTED_EXTS.add(".pdf")
except Exception:
    pass


# ============================================================
# カラーSVGアイコン（Lucide風・木目背景に合うモダン配色）
# ============================================================

_SVG_ICON_CACHE: dict = {}

# ツールバーは「黒線＋丸囲み」で統一する
_ICON_LINE_COLOR = "#1a1a1a"


def _circled(glyph: str) -> str:
    """グリフを丸枠の中に縮小配置する。線幅は縮小率を補正して外周と揃える。"""
    return (
        '<circle cx="12" cy="12" r="10"/>'
        '<g transform="translate(12 12) scale(0.55) translate(-12 -12)" '
        f'stroke-width="3.4">{glyph}</g>'
    )


_TOOLBAR_SVG = {
    "home":     _circled('<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
                         '<polyline points="9 22 9 12 15 12 15 22"/>'),
    # 丸囲み矢印・時計はLucideに元からあるのでそのまま使う
    "up":       ('<circle cx="12" cy="12" r="10"/>'
                 '<path d="m16 12-4-4-4 4"/><path d="M12 16V8"/>'),
    "refresh":  _circled('<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
                         '<path d="M21 3v5h-5"/>'
                         '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
                         '<path d="M8 16H3v5"/>'),
    "history":  ('<circle cx="12" cy="12" r="10"/>'
                 '<polyline points="12 6 12 12 16 14"/>'),
    "back":     ('<circle cx="12" cy="12" r="10"/>'
                 '<path d="m12 8-4 4 4 4"/><path d="M16 12H8"/>'),
    "settings": _circled('<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0'
                         'l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72'
                         'v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73'
                         'l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 '
                         '2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73'
                         'l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74'
                         'l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0'
                         'l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
                         '<circle cx="12" cy="12" r="3"/>'),
    # 丸囲みの？（Lucide help-circle 相当）
    "help":     ('<circle cx="12" cy="12" r="10"/>'
                 '<path d="M9.1 9a3 3 0 1 1 5.2 2c-.6.6-1.3 1-1.3 2"/>'
                 '<path d="M12 17h.01"/>'),
    "sort":     _circled('<path d="m3 8 4-4 4 4"/><path d="M7 4v16"/>'
                         '<path d="m21 16-4 4-4-4"/><path d="M17 20V4"/>'),
    "filter":   _circled('<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>'),
    "stats":    _circled('<line x1="12" y1="20" x2="12" y2="10"/>'
                         '<line x1="18" y1="20" x2="18" y2="4"/>'
                         '<line x1="6" y1="20" x2="6" y2="16"/>'),
    # 虫眼鏡（サムネイルサイズのクイック切替）
    "zoom":     ('<circle cx="11" cy="11" r="8"/>'
                 '<path d="m21 21-4.3-4.3"/>'
                 '<line x1="11" y1="8" x2="11" y2="14"/>'
                 '<line x1="8" y1="11" x2="14" y2="11"/>'),
    # 丸囲みの＋（本棚への追加）
    "add":      ('<circle cx="12" cy="12" r="10"/>'
                 '<path d="M12 8v8"/><path d="M8 12h8"/>'),
    "folder_add": _circled('<path d="M12 10v6"/><path d="M9 13h6"/>'
                           '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9'
                           'A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>'),
    "file_add": _circled('<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
                         '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
                         '<path d="M9 15h6"/><path d="M12 18v-6"/>'),
}

# 本棚アイテム用（塗りつぶしのモダンなフォルダ / 画像ファイル）
_FOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<defs><linearGradient id="fg" x1="0" y1="8" x2="0" y2="20" gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#ffd43b"/><stop offset="1" stop-color="#f5a000"/>'
    '</linearGradient></defs>'
    '<path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h5.2l2 2.5h9.8A1.5 1.5 0 0 1 22 8v1H2z" fill="#e8930c"/>'
    '<rect x="2" y="8.2" width="20" height="11.8" rx="1.8" fill="url(#fg)"/>'
    '</svg>'
)
_IMAGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    '<rect x="3" y="3" width="18" height="18" rx="2.5" fill="#4dabf7"/>'
    '<circle cx="8.5" cy="8.5" r="2" fill="#fff3bf"/>'
    '<path d="M4.5 19.5 10 12.5l4 4.5 2.5-3 3 3.5v.5a1.5 1.5 0 0 1-1.5 1.5H6'
    'a1.5 1.5 0 0 1-1.5-1.5z" fill="#1864ab"/>'
    '</svg>'
)


def _render_svg_icon(svg: str, size: int = 64) -> QIcon | None:
    """SVG文字列をQIconに変換する。QtSvgが使えない環境ではNone。"""
    try:
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        renderer.render(p)
        p.end()
        return QIcon(pix)
    except Exception:
        return None


def toolbar_icon(key: str, theme_fallback: str = "") -> QIcon:
    """カラーの線画アイコンを返す（キャッシュ付き）"""
    if key in _SVG_ICON_CACHE:
        return _SVG_ICON_CACHE[key]
    inner = _TOOLBAR_SVG[key]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{_ICON_LINE_COLOR}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{inner}</svg>'
    )
    icon = _render_svg_icon(svg)
    if icon is None:
        icon = QIcon.fromTheme(theme_fallback) if theme_fallback else QIcon()
    _SVG_ICON_CACHE[key] = icon
    return icon


def folder_icon() -> QIcon:
    """本棚アイテム用のフォルダアイコン（アンバーの塗りつぶし）"""
    if "folder" not in _SVG_ICON_CACHE:
        icon = _render_svg_icon(_FOLDER_SVG, size=256)
        if icon is None:
            icon = QIcon.fromTheme("folder")
            if icon.isNull():
                icon = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        _SVG_ICON_CACHE["folder"] = icon
    return _SVG_ICON_CACHE["folder"]


def image_file_icon() -> QIcon:
    """本棚アイテム用の画像ファイルアイコン"""
    if "image_file" not in _SVG_ICON_CACHE:
        icon = _render_svg_icon(_IMAGE_SVG, size=256)
        if icon is None:
            icon = QIcon.fromTheme("image-x-generic")
            if icon.isNull():
                icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
        _SVG_ICON_CACHE["image_file"] = icon
    return _SVG_ICON_CACHE["image_file"]


def pil_to_qpixmap(pil_image):
    if pil_image is None:
        return None
    pil_image = pil_image.convert("RGB")
    data = pil_image.tobytes("raw", "RGB")
    stride = pil_image.width * 3
    qimage = QImage(data, pil_image.width, pil_image.height, stride, QImage.Format_RGB888)
    return QPixmap.fromImage(qimage)


# ============================================================
# ディレクトリ列挙ワーカー
class StartupCheckWorker(QObject):
    """
    起動時の last_book / last_book_folder / folder の存在チェックを
    バックグラウンドで行う（ネットワークドライブのスピンアップ中に
    UIをフリーズさせないため）。
    """
    done = Signal(dict)  # {"last_book": str|None, "last_book_folder": str|None, "folder": str|None}

    def __init__(self, last_book: str | None, last_book_folder: str | None, folder: str | None):
        super().__init__()
        self._last_book = last_book
        self._last_book_folder = last_book_folder
        self._folder = folder

    def run(self):
        result = {"last_book": None, "last_book_folder": None, "folder": None}
        try:
            if self._last_book and Path(self._last_book).exists():
                result["last_book"] = self._last_book
        except Exception:
            pass
        try:
            if self._last_book_folder and Path(self._last_book_folder).exists():
                result["last_book_folder"] = self._last_book_folder
        except Exception:
            pass
        try:
            if self._folder and Path(self._folder).exists():
                result["folder"] = self._folder
        except Exception:
            pass
        self.done.emit(result)


# ============================================================

class DirScanWorker(QObject):
    # (path_str, is_dir) のタプルリストを返す
    scan_done = Signal(list, int)   # ([(path_str, is_dir), ...], generation)
    progress  = Signal(int, int, int)  # (done, total, generation)

    def __init__(self, folder: str | None, registered_items: list[str], generation: int):
        super().__init__()
        self._folder = folder
        self._registered = registered_items
        self._generation = generation

    def run(self):
        result = []
        try:
            if self._folder is None:
                items = self._registered
                total = len(items)
                for i, p_str in enumerate(items):
                    p = Path(p_str)
                    try:
                        result.append((p_str, p.is_dir()))
                    except Exception:
                        result.append((p_str, not bool(p.suffix)))
                    if total > 0 and i % 10 == 0:
                        self.progress.emit(i + 1, total, self._generation)
            else:
                # os.scandir を使う: DirEntry.is_dir() は追加statコールなし
                # （NTFSおよびSMBネットワークドライブでは一覧取得時に属性が含まれる）
                import os
                from utils import natural_sort_key
                with os.scandir(self._folder) as sd:
                    entries = sorted(
                        [e for e in sd if not e.name.startswith('.')],
                        key=lambda e: natural_sort_key(e.name)
                    )
                total = len(entries)
                for i, entry in enumerate(entries):
                    try:
                        result.append((entry.path, entry.is_dir()))
                    except Exception:
                        result.append((entry.path, not bool(Path(entry.name).suffix)))
                    # 10件ごとに進捗通知（シグナル発行コストを抑える）
                    if total > 0 and (i % 10 == 0 or i == total - 1):
                        self.progress.emit(i + 1, total, self._generation)
        except Exception as e:
            print(f"DirScanWorker エラー: {e}")
        self.scan_done.emit(result, self._generation)


# ============================================================
# 検索ワーカー（バックグラウンドでフォルダ配下を再帰検索）
# ============================================================

class SearchWorker(QObject):
    result_ready = Signal(list, int)   # (matched_paths, generation)
    finished     = Signal()

    def __init__(self, root_paths: list[str], query: str, generation: int):
        super().__init__()
        self._roots      = root_paths
        self._query      = query.lower()
        self._generation = generation
        self._stopped    = False

    def stop(self):
        self._stopped = True

    def run(self):
        from core import get_cache_path
        results = []
        for root_str in self._roots:
            if self._stopped:
                break
            root = Path(root_str)
            try:
                self._search_dir(root, results)
            except Exception as e:
                print(f"検索エラー {root}: {e}")
        self.result_ready.emit(results, self._generation)
        self.finished.emit()

    def _search_dir(self, directory: Path, results: list):
        try:
            for p in directory.iterdir():
                if self._stopped:
                    return
                if p.name.startswith('.'):
                    continue
                name_lower = p.name.lower()
                if self._query in name_lower:
                    if p.is_dir() or p.suffix.lower() in SUPPORTED_EXTS:
                        results.append(str(p))
                if p.is_dir():
                    self._search_dir(p, results)
        except PermissionError:
            pass


# ============================================================
# 木目背景 + 棚板影 付き QListView
# ============================================================

class WoodListView(QListView):
    """
    木目テクスチャを背景に持ち、各段の下端に棚板と影を描画する
    QListView のサブクラス。

    木目: styleSheet の background-image に一時PNGファイルパスを指定
    棚板: paintEvent で super() の後に viewport 上に重ねて描画
    """

    _WOOD_CACHE_PATH = str(APP_DIR / "wood_cache.png")

    # スクロール後300msデバウンスして通知（BookshelfWindowがPixmap退避に使う）
    scroll_stabilized = Signal()

    # エクスプローラー等からファイル/フォルダがドロップされたとき（ローカルパスのリスト）
    files_dropped = Signal(list)
    manual_layout_changed = Signal()  # 手動配置モードで並びが変わった（全位置を保存する契機）
    item_activated = Signal(object)   # Return/Enterでカレント項目を開く（QModelIndex）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._manual_mode = False
        self._manual_cols = 1  # 手動配置モード: 現在の表示列数（保存位置の計算に使う）
        self._press_row = -1        # 手動配置: マウス押下したアイテムの行
        self._manual_dragging = False  # 手動配置: ドラッグ中か
        self._drop_target_row = -1  # 手動配置: ドラッグ中のドロップ先ハイライト行
        self._wood_generated = False
        self._wood_pixmap: QPixmap | None = None
        self._scroll_evict_timer: QTimer | None = None
        self._wood_timer = None
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideNone)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self._scroll_evict_timer is None:
            self._scroll_evict_timer = QTimer(self)
            self._scroll_evict_timer.setSingleShot(True)
            self._scroll_evict_timer.timeout.connect(self.scroll_stabilized)
        self._scroll_evict_timer.start(300)

    # ------------------------------------------------------------------ #
    # ドラッグ＆ドロップ登録
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event):
        # 外部（エクスプローラー等）からのファイルドロップのみ扱う。
        # 手動配置の並べ替えはQtの内部ドラッグではなくマウスイベントで自前実装している。
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def set_manual_mode(self, enabled: bool):
        """手動配置モード: アイテムをドラッグして段の好きな位置へ入れ替えられるようにする。

        Qtの内部ドラッグ（startDrag/QDrag.exec）は、ウィンドウリサイズ時の位置再計算や
        ドラッグ中の currentIndex 追従など環境依存の不安定さが繰り返し確認されたため使わない。
        代わりに mousePress/Move/Release で並べ替えを自前実装する（Movementは常にStatic、
        位置はモデルの行順で表現し、空き段はプレースホルダー行で埋める）。
        """
        self._manual_mode = enabled
        # Qtの内部アイテムドラッグは無効（外部ファイルドロップは
        # setAcceptDrops(True)＋dropEventオーバーライドで別途処理される）。
        self.setDragEnabled(False)
        self.setDragDropMode(QListView.NoDragDrop)

    def _swap_rows(self, r1: int, r2: int):
        """モデル上の2行を入れ替える（Static配置なのでQtが自動的に再描画する）。
        空セル（プレースホルダー行）との入れ替えも同じ仕組みで扱える。"""
        if r1 == r2:
            return
        model = self.model()
        if r1 > r2:
            r1, r2 = r2, r1
        items2 = model.takeRow(r2)
        items1 = model.takeRow(r1)
        model.insertRow(r1, items2)
        model.insertRow(r2, items1)

    # ------------------------------------------------------------------ #
    # 手動配置の並べ替え（マウスイベント直接方式・Qt内部ドラッグ不使用）
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        self._press_row = -1
        self._manual_dragging = False
        if self._manual_mode and event.button() == Qt.LeftButton:
            idx = self.indexAt(event.position().toPoint())
            if idx.isValid() and idx.data(Qt.UserRole):
                self._press_row = idx.row()
                self._press_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._manual_mode and self._press_row >= 0
                and (event.buttons() & Qt.LeftButton)):
            if not self._manual_dragging:
                dist = (event.position().toPoint() - self._press_pos).manhattanLength()
                from PySide6.QtWidgets import QApplication as _QApp
                if dist >= _QApp.startDragDistance():
                    self._manual_dragging = True
                    self.setCursor(Qt.ClosedHandCursor)
            if self._manual_dragging:
                # ドロップ先セルを追跡してハイライトを更新する
                tgt = self.indexAt(event.position().toPoint())
                new_row = tgt.row() if tgt.isValid() else -1
                if new_row != self._drop_target_row:
                    self._drop_target_row = new_row
                    self.viewport().update()
            # ドラッグ中はラバーバンド選択・自動スクロールを起こさないよう super を呼ばない
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (self._manual_mode and event.button() == Qt.LeftButton
                and self._manual_dragging and self._press_row >= 0):
            self.unsetCursor()
            tgt = self.indexAt(event.position().toPoint())
            if (tgt.isValid() and tgt.row() != self._press_row
                    and self._press_row < self.model().rowCount()):
                # ドロップ先が空席（プレースホルダー）でも入れ替えれば、
                # ドラッグしたアイテムが空セルへ移り、空席が元の位置に入る。
                self._swap_rows(self._press_row, tgt.row())
                self.manual_layout_changed.emit()
            self.clearSelection()
            self.selectionModel().clearCurrentIndex()
            self._press_row = -1
            self._manual_dragging = False
            self._drop_target_row = -1
            self.viewport().update()
            event.accept()
            return
        self._press_row = -1
        self._manual_dragging = False
        self._drop_target_row = -1
        super().mouseReleaseEvent(event)

    def dropEvent(self, event):
        # 外部（エクスプローラー等）からのファイルドロップのみ扱う
        if event.mimeData().hasUrls():
            paths = [
                url.toLocalFile() for url in event.mimeData().urls()
                if url.isLocalFile()
            ]
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        # Return/Enter: カレント項目を開く（フォルダは中へ、本はビューアで開く）
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            idx = self.currentIndex()
            if idx.isValid() and idx.data(Qt.UserRole):
                self.item_activated.emit(idx)
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        """1スクロールで1段（1行分）だけ移動する"""
        row_h = self.sizeHintForRow(0)
        if row_h <= 0:
            super().wheelEvent(event)
            return
        # angleDelta は通常±120単位（1ノッチ）
        delta = event.angleDelta().y()
        if delta == 0:
            super().wheelEvent(event)
            return
        # 上方向(正)なら -row_h、下方向(負)なら +row_h
        steps = -1 if delta > 0 else 1
        sb = self.verticalScrollBar()
        sb.setValue(sb.value() + steps * row_h)
        event.accept()

    def generate_wood_background(self):
        """木目テクスチャを生成してstyleSheetに反映する"""
        try:
            from wood_bg import _generate_wood_pil, generate_wood_pixmap
            w = max(self.width(), 800)
            h = max(self.height(), 400)
            pil_img = _generate_wood_pil(min(w, 1000), min(h, 800))
            Path(self._WOOD_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
            pil_img.save(self._WOOD_CACHE_PATH)
            # resizeEventのサイズ比較用にpixmapを保持
            self._wood_pixmap = generate_wood_pixmap(w, h)
            self._apply_wood_stylesheet()
            self._wood_generated = True
            # ウィンドウ全体のテーマも更新
            win = self.window()
            if hasattr(win, '_apply_wood_theme'):
                win._apply_wood_theme(self._WOOD_CACHE_PATH)
        except Exception as e:
            print(f"木目生成エラー: {e}")

    def _apply_wood_stylesheet(self):
        path = self._WOOD_CACHE_PATH.replace("\\", "/")
        self.setStyleSheet(f"""
            QListView {{
                background-image: url("{path}");
                background-repeat: repeat-x;
                background-attachment: fixed;
                border: 2px solid #8b6020;
                border-radius: 10px;
                color: #1a0e00;
            }}
            QListView::item {{
                background: transparent;
                border: none;
            }}
            QListView::item:hover {{
                background: transparent;
                border: none;
            }}
            QListView::item:selected {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: rgba(180,130,70,80);
                width: 10px; border-radius: 5px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(140,95,40,180);
                border-radius: 5px; min-height: 20px;
            }}
        """)

    def paintEvent(self, event):
        # まずQListViewの標準描画（アイテム）
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # 手動配置ドラッグ中: ドロップ先セルを選択色（マウスフォーカスと同色）で強調
        if self._manual_dragging and self._drop_target_row >= 0:
            model = self.model()
            if model and self._drop_target_row < model.rowCount():
                idx = model.index(self._drop_target_row, 0)
                rect = self.visualRect(idx)
                if rect.isValid():
                    from PySide6.QtGui import QPen
                    painter.setRenderHint(QPainter.Antialiasing, True)
                    painter.fillRect(rect, QColor(80, 120, 200, 140))
                    painter.setPen(QPen(QColor(80, 120, 200, 220), 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawRect(rect.adjusted(1, 1, -1, -1))
                    painter.setRenderHint(QPainter.Antialiasing, False)
        # その上に棚板と影を重ねる
        self._draw_shelf_boards(painter)
        painter.end()

    def _update_grid_size(self):
        """ビューポート幅いっぱいにアイテムが均等配置されるようgridSizeを動的調整する。
        手動配置モードでも Static のままなので通常通り setGridSize してよい
        （Free movement をやめたことで setGridSize がアイテム位置を壊す問題も解消した）。
        _manual_cols も同時に更新し、ドロップ時の行↔(段,列)変換に使う。
        """
        vp_w = self.viewport().width()
        if vp_w <= 0:
            return
        natural_w = self.sizeHintForColumn(0)
        if natural_w <= 0:
            natural_w = self.iconSize().width() + 4   # H_MARGIN * 2 フォールバック
        natural_h = self.sizeHintForRow(0)
        if natural_h <= 0:
            return

        # スクロールバー振動対策:
        # ScrollBarAsNeeded では「スクロールバーが出る→viewport幅が縮む→列数/セル幅を
        # 再計算→レイアウトが変わってスクロールバーが引っ込む→幅が戻る…」という
        # 発振ループが特定の幅で発生し、アイコンが高速に描画/消去を繰り返す。
        # これを防ぐため、スクロールバーが現在非表示のときは常にその幅を差し引いた
        # 「安定幅」で列数を決める（＝スクロールバーの有無で列数が変わらないようにする）。
        sb = self.verticalScrollBar()
        if (self.verticalScrollBarPolicy() != Qt.ScrollBarAlwaysOff
                and not sb.isVisible()):
            vp_w = max(1, vp_w - sb.sizeHint().width())

        cols = max(1, vp_w // natural_w)
        self._manual_cols = cols
        cell_w = vp_w // cols
        new_grid = QSize(cell_w, natural_h)
        # 変化がなければ setGridSize を呼ばない（無駄な再レイアウトを避ける）
        if self.gridSize() != new_grid:
            self.setGridSize(new_grid)

    def rowsInserted(self, parent, start, end):
        super().rowsInserted(parent, start, end)
        if start == 0:   # 最初のアイテム追加時にグリッドサイズを設定
            self._update_grid_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid_size()
        # 左下フローティング（パンくず等）の再配置
        cb = getattr(self, 'overlay_reposition_cb', None)
        if cb:
            cb()
        # 再帰防止フラグ
        if getattr(self, '_in_resize', False):
            return
        self._in_resize = True
        try:
            # 微小変化（50px未満）は無視
            if self._wood_pixmap is not None:
                if (abs(self.width()  - self._wood_pixmap.width())  < 50 and
                    abs(self.height() - self._wood_pixmap.height()) < 50):
                    return
            self._wood_generated = False
            # デバウンス: タイマーをリセットして500ms後に1回だけ再生成
            if self._wood_timer is None:
                self._wood_timer = QTimer(self)
                self._wood_timer.setSingleShot(True)
                self._wood_timer.timeout.connect(self.generate_wood_background)
            self._wood_timer.start(500)
        finally:
            self._in_resize = False

    def _draw_shelf_boards(self, painter: QPainter):
        """各段の下端に棚板と影を描画する（空の段もビューポートを埋めるまで描く）"""
        model = self.model()
        if not model:
            return

        item_h = self.sizeHintForRow(0)
        if item_h <= 0:
            item_h = self.gridSize().height()
        if item_h <= 0:
            return

        # アルファ付きグラデーションを正しく描画するため明示設定
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        scroll_y = self.verticalScrollBar().value()
        vp_w = self.viewport().width()
        vp_h = self.viewport().height()

        item_w = self.sizeHintForColumn(0)
        if item_w <= 0:
            item_w = self.iconSize().width() + 40
        cols = max(1, vp_w // max(item_w + self.spacing(), 1))
        rows = (model.rowCount() + cols - 1) // cols
        # アイテムがない段にも棚板を描画する（本棚らしい見た目＋手動配置の受け皿）
        row_h = max(1, item_h + self.spacing())
        rows = max(rows, (scroll_y + vp_h) // row_h + 1)

        BOARD_H  = 16
        SHADOW_H = 14

        for row in range(rows):
            row_bottom = (row + 1) * (item_h + self.spacing()) - scroll_y
            if row_bottom < 0 or row_bottom - BOARD_H > vp_h:
                continue
            board_top = row_bottom - BOARD_H

            # ハイライト（棚板上端の明るい線）
            hl = QLinearGradient(0, board_top, 0, board_top + 4)
            hl.setColorAt(0.0, QColor(255, 245, 210, 180))
            hl.setColorAt(1.0, QColor(255, 245, 210,   0))
            painter.fillRect(QRect(0, board_top, vp_w, 4), QBrush(hl))

            # 棚板本体
            bg = QLinearGradient(0, board_top, 0, row_bottom)
            bg.setColorAt(0.0, QColor(210, 168, 108, 220))
            bg.setColorAt(1.0, QColor(168, 128,  78, 225))
            painter.fillRect(QRect(0, board_top, vp_w, BOARD_H), QBrush(bg))

            # 棚板下の影（透明端を木目色ベースにして黒を防ぐ）
            sh = QLinearGradient(0, row_bottom, 0, row_bottom + SHADOW_H)
            sh.setColorAt(0.0, QColor(50, 28,  8, 170))
            sh.setColorAt(1.0, QColor(50, 28,  8,   0))
            sh.setSpread(QLinearGradient.PadSpread)
            painter.fillRect(QRect(0, row_bottom, vp_w, SHADOW_H), QBrush(sh))


# ============================================================
# カスタムアイテムデリゲート
# レイアウト: [テキスト(上)] [サムネイル(下揃え)]
# 各段のサムネイル底辺を揃えるため、全アイテムの高さを均一にする
# ============================================================

class BookshelfDelegate(QStyledItemDelegate):
    """
    pico viewer 風レイアウト:
      - テキスト（タイトル）がサムネイルの上に折り返し表示
      - サムネイルは下揃え（底辺が段ごとに一致）
      - アイテム高さは固定（テキスト領域 + サムネイル領域）
    """

    H_MARGIN   = 2    # 左右余白
    V_MARGIN   = 2    # 上下余白
    TOP_OFFSET = 14   # 前段の影が被るので上端からこのpx分下げてテキストを描画
    TEXT_LINES = 3
    FONT_SIZE  = 9

    def _text_area_height(self, fm) -> int:
        return fm.lineSpacing() * self.TEXT_LINES + fm.descent() + self.V_MARGIN

    def paint(self, painter: QPainter, option, index):
        if index.data(PLACEHOLDER_ROLE):
            return  # 手動配置モードの空き段: 何も描画しない
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        rect      = option.rect
        text      = index.data(TITLE_ROLE) or index.data(Qt.DisplayRole) or ""
        icon      = index.data(Qt.DecorationRole)

        # フォントを先に設定してからfm・text_hを計算
        font = painter.font()
        font.setPointSize(self.FONT_SIZE)
        painter.setFont(font)
        fm     = painter.fontMetrics()
        text_h = self._text_area_height(fm)

        # ---- 選択・ホバーハイライト ----
        # Qtのデフォルトスタイル描画は呼ばない（黒矩形の原因になる）
        if option.state & QStyle.State_Selected:
            sel_color = QColor(80, 120, 200, 140)
            painter.fillRect(rect, sel_color)
            text_color = QColor(255, 255, 255)
        elif option.state & QStyle.State_MouseOver:
            hover_color = QColor(255, 230, 160, 80)
            painter.fillRect(rect, hover_color)
            text_color = QColor(30, 20, 10)
        else:
            text_color = QColor(30, 20, 10)

        # ---- テキスト領域（上部・前段の影分だけ下げる） ----
        text_rect = QRect(
            rect.left()  + self.H_MARGIN,
            rect.top()   + self.TOP_OFFSET + self.V_MARGIN,
            rect.width() - self.H_MARGIN * 2,
            text_h,
        )
        painter.setPen(text_color)
        fm = painter.fontMetrics()

        # しおり（テキスト左側）の幅を確保
        progress = index.data(PROGRESS_ROLE)
        bookmark_w = 0
        if progress in ('reading', 'done'):
            bookmark_w = 14  # しおり分のインデント

        text_rect2 = QRect(
            text_rect.left() + bookmark_w,
            text_rect.top(),
            text_rect.width() - bookmark_w,
            text_rect.height(),
        )

        # 省略判定の基準高さ = テキスト領域の高さと同じ
        max_h     = text_h
        w         = text_rect2.width()
        wrap_flag = Qt.TextWrapAnywhere | Qt.AlignHCenter

        def fits(t: str) -> bool:
            return fm.boundingRect(QRect(0, 0, w, 10000), wrap_flag, t).height() <= max_h

        if fits(text):
            display_text = text
        else:
            ellipsis = "…"
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if fits(text[:mid] + ellipsis):
                    lo = mid
                else:
                    hi = mid - 1
            display_text = text[:lo] + ellipsis

        painter.drawText(
            text_rect2,
            wrap_flag | Qt.AlignTop,
            display_text
        )

        # しおり描画（テキスト左端、1行目の高さに合わせる）
        if bookmark_w:
            bm_w = 12
            bm_h = 16
            bm_x = text_rect.left()
            bm_y = text_rect.top() + 1
            color = QColor(30, 100, 220, 230) if progress == 'done' else QColor(210, 40, 40, 230)
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            from PySide6.QtGui import QPolygon
            from PySide6.QtCore import QPoint
            poly = QPolygon([
                QPoint(bm_x,          bm_y),
                QPoint(bm_x + bm_w,   bm_y),
                QPoint(bm_x + bm_w,   bm_y + bm_h),
                QPoint(bm_x + bm_w//2, bm_y + bm_h - 5),
                QPoint(bm_x,          bm_y + bm_h),
            ])
            painter.drawPolygon(poly)
            painter.restore()

        # ---- サムネイル・アイコン領域（棚板の上に収まるよう BOARD_H 分上げる） ----
        img_area_h = rect.height() - self.TOP_OFFSET - text_h - self.V_MARGIN * 2 - self.BOARD_H
        img_area_w = rect.width()  - self.H_MARGIN * 2
        area_left  = rect.left() + self.H_MARGIN
        area_top   = rect.top()  + self.TOP_OFFSET + text_h + self.V_MARGIN

        is_dir = index.data(IS_DIR_ROLE)
        if is_dir is None:
            is_dir = not bool(Path(index.data(Qt.UserRole) or "").rsplit('.', 1)[-1] if '.' in (index.data(Qt.UserRole) or "") else "")

        if is_dir:
            icon = index.data(Qt.DecorationRole)
            if icon and not icon.isNull():
                icon_rect = QRect(area_left, area_top, img_area_w, img_area_h)
                icon.paint(painter, icon_rect, Qt.AlignCenter)
        else:
            # PIXMAP_ROLEから直接QPixmapを取得（QIconを経由しない）
            px = index.data(PIXMAP_ROLE)
            if px and not px.isNull():
                scaled = px.scaled(
                    img_area_w, img_area_h,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                # 幅が余る場合、幅基準で再スケール（高さ制限内で）
                if scaled.width() < img_area_w and px.width() > 0:
                    w_scale = img_area_w / px.width()
                    new_h = int(px.height() * w_scale)
                    if new_h <= img_area_h:
                        scaled = px.scaled(
                            img_area_w, new_h,
                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation
                        )
                x = area_left + (img_area_w - scaled.width()) // 2
                y = area_top  + (img_area_h - scaled.height())
                painter.drawPixmap(x, y, scaled)

                
                # キャッシュ済みマークを右下に描画
                if index.data(CACHED_ROLE):
                    # キャッシュ済みマーク（青丸に白抜き「C」）
                    mark_size = 22
                    mx = x + scaled.width()  - mark_size - 3
                    my = y + scaled.height() - mark_size - 3
                    painter.save()
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(QColor(30, 100, 220, 230))
                    painter.drawEllipse(mx, my, mark_size, mark_size)
                    painter.setPen(QColor(255, 255, 255))
                    font = painter.font()
                    font.setPixelSize(13)
                    font.setBold(True)
                    painter.setFont(font)
                    painter.drawText(QRect(mx, my, mark_size, mark_size),
                                     Qt.AlignCenter, "C")
                    painter.restore()
            else:
                # プレースホルダー（未生成）はフォルダアイコン代わりに空白
                pass

        painter.restore()

    BOARD_H = 16

    def _make_font(self, base_font):
        from PySide6.QtGui import QFont
        f = QFont(base_font)
        f.setPointSize(self.FONT_SIZE)
        return f

    def sizeHint(self, option, index):
        icon_size = option.decorationSize
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self._make_font(option.font))
        text_h = self._text_area_height(fm)
        w = icon_size.width() + self.H_MARGIN * 2
        h = self.TOP_OFFSET + text_h + icon_size.height() + self.V_MARGIN * 2 + self.BOARD_H
        return QSize(w, h)


# ============================================================
# サムネイルワーカー
# ============================================================

class ThumbnailWorker(QObject):
    # バッチシグナル: 複数枚まとめて送ることでUIスレッドの呼び出し回数を削減
    thumbnails_batch = Signal(object, int)  # ([(path_str, QPixmap), ...], generation)
    finished         = Signal()


    BATCH_SIZE = 1    # 1件できたらすぐ送信（大量ファイルでも逐次表示）

    def __init__(self, paths: list[str], generation: int, thumb_size: tuple = (190, 270)):
        super().__init__()
        self._paths = paths
        self._generation = generation
        self._thumb_size = thumb_size
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        from PIL import Image
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # ① キャッシュ確認 + ZIP/RAR分離
        cached_paths = []
        uncached_zip = []
        uncached_rar = []

        for path_str in self._paths:
            if self._stopped:
                self.finished.emit()
                return
            if get_cache_path(Path(path_str)).exists():
                cached_paths.append(path_str)
            else:
                suffix = Path(path_str).suffix.lower()
                if suffix in ('.zip', '.cbz'):
                    uncached_zip.append(path_str)
                else:
                    uncached_rar.append(path_str)

        def make_thumb(path_str: str):
            """サムネイル生成（スレッドプール内で実行）"""
            if self._stopped:
                return path_str, None
            try:
                p = Path(path_str)
                cache = get_cache_path(p)
                if cache.exists():
                    # プレースホルダーも含めてキャッシュから読む
                    img = Image.open(cache)
                    img.load()
                else:
                    img = create_thumbnail(p, size=self._thumb_size)
                if img:
                    # 表示サイズに縮小してからQPixmapに変換（メモリ節約）
                    img.thumbnail(self._thumb_size, Image.LANCZOS)
                    return path_str, pil_to_qpixmap(img)
            except Exception:
                pass
            return path_str, None

        def process_batch(paths: list[str], workers: int = 4):
            """並列処理して結果をできた順にemit"""
            if not paths:
                return
            # withを使わず手動管理: stop()時にcancel_futures=Trueで即座にキャンセルする
            # （withのcontextmanager exitはsubmit済み全futuresを待つため停止できない）
            ex = ThreadPoolExecutor(max_workers=workers)
            futures = {ex.submit(make_thumb, p): p for p in paths}
            try:
                for future in as_completed(futures):
                    if self._stopped:
                        break
                    path_str, pixmap = future.result()
                    if pixmap:
                        self.thumbnails_batch.emit(
                            [(path_str, pixmap)], self._generation
                        )
            finally:
                ex.shutdown(wait=False, cancel_futures=True)

        # ② キャッシュあり → 並列読み込み（最優先・ローカルなので高速）
        process_batch(cached_paths, workers=8)

        # ③ ZIPキャッシュなし → 並列生成（ネットワークI/Oを並列化）
        process_batch(uncached_zip, workers=4)

        # ④ RARキャッシュなし
        # libarchive は archive_t オブジェクト単位でスレッドセーフ。
        # 各スレッドが独立した archive_read_new() を使うため並列処理は安全。
        # RAR はデータ展開が重いためワーカー数は控えめに 2 とする。
        if uncached_rar:
            process_batch(uncached_rar, workers=2)

        self.finished.emit()


# ============================================================
# メインウィンドウ
# ============================================================

class SearchLineEdit(QLineEdit):
    """検索ボックス専用QLineEdit。Enter で検索を発火する（IME確定のEnterは除く）。"""
    search_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ime_just_committed = False

    def inputMethodEvent(self, event):
        if event.commitString():
            self._ime_just_committed = True
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        # Enter → 検索（IME確定直後は除く）
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._ime_just_committed:
                self.search_requested.emit()
            self._ime_just_committed = False
            return
        self._ime_just_committed = False
        super().keyPressEvent(event)


class BookshelfWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("window_title_shelf"))
        self.resize(1440, 920)
        # 木目生成前のフォールバック背景色
        self.setStyleSheet("QMainWindow { background-color: #e8d5a0; }")

        self.settings = load_settings()

        self.library_root = APP_DIR
        self.library_root.mkdir(parents=True, exist_ok=True)

        self.registered_items = self.load_library()
        self.current_folder = None
        self._viewer_windows = []
        self._inline_viewer: ViewerWindow | None = None

        # スレッド管理: Noneにするのではなく参照を保持して安全に停止する
        self._scan_thread:  QThread | None = None
        self._scan_worker:  DirScanWorker | None = None
        self._startup_thread: QThread | None = None
        self._startup_worker: StartupCheckWorker | None = None
        self._was_maximized_before_fullscreen: bool = False
        self._thumb_thread: QThread | None = None
        self._thumb_worker: ThumbnailWorker | None = None

        self._search_thread: QThread | None = None
        self._search_worker: SearchWorker | None = None
        self._is_searching: bool = False
        self._saved_scroll_path: str | None = None
        self._pending_back_scroll: str | None = None
        self._last_scroll_path: str | None = None
        self._viewer_file_path: str | None = None  # ビューアで開いていたファイルパス

        # 世代番号: フォルダ移動のたびに増加。古いワーカーの結果を無視するために使う
        self._view_generation: int = 0

        # Pixmap LRU: RAMに保持するQPixmapを最大_PIXMAP_MAX件に制限する
        from collections import OrderedDict
        self._pixmap_lru: OrderedDict = OrderedDict()
        self._series_view = None       # シリーズ内表示中: (タイトル, [パス, ...])
        self._selected_crumb = None    # パンくず末尾に出す選択アイテム名（クリックで更新）
        self._series_groups: dict = {} # 代表パス → シリーズ構成パスリスト   # path_str → QStandardItem
        self._shelf_layout_cache: dict | None = None  # shelf_layout.json のメモリキャッシュ
        # ウィンドウ型ロード用: 現在Pixmapが入っているモデル行番号の集合
        self._loaded_rows: set[int] = set()
        # ソフト停止した旧スレッドを自然終了まで保持するリスト（GC防止）
        self._zombie_threads: list = []

        # current_folderの復元はバックグラウンドで行う（_restore_and_refresh内）
        # ネットワークドライブのスピンアップ中にUIがフリーズしないようにするため
        self.current_folder = None

        self.create_toolbar()
        self.create_menubar()
        self._build_central()

        # スクロールが止まった300ms後: ウィンドウを再計算してPixmapを入れ替える
        self.list_view.scroll_stabilized.connect(self._load_window_thumbnails)

        # エクスプローラー等からのドロップで本棚に登録
        self.list_view.files_dropped.connect(self._on_files_dropped)
        # 手動配置モード
        self.list_view.manual_layout_changed.connect(self._on_manual_layout_changed)
        self.list_view.set_manual_mode(self.settings.get("shelf_sort") == "manual")

        self._restore_window_state()
        # まずルート本棚を即表示し、last_book等の存在チェックはバックグラウンドで行う
        QTimer.singleShot(0, self._restore_and_refresh)
        QTimer.singleShot(200, self.list_view.generate_wood_background)
        QTimer.singleShot(900, self._show_after_restore)

    # ------------------------------------------------------------------ #
    # UI 構築
    # ------------------------------------------------------------------ #

    def _build_central(self):
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        shelf_widget = QWidget()
        shelf_widget.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(shelf_widget)
        layout.setContentsMargins(20, 10, 20, 20)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)

        # 旧 path_label は互換のため残す（一部処理が参照するが表示はしない）。
        self.path_label = QLabel()
        self.path_label.setVisible(False)

        # パンくずリストは本棚(list_view)の左下にフローティング表示する
        # （_build_central 後半で list_view を親に付け替える）。
        self.breadcrumb_bar = QWidget()
        self.breadcrumb_bar.setStyleSheet(
            "background: rgba(255,255,255,0.92); border-radius: 6px;"
            "border: 1px solid rgba(150,110,60,120);"
        )
        self.breadcrumb_bar.setSizePolicy(SP.Maximum, SP.Maximum)
        self.breadcrumb_layout = QHBoxLayout(self.breadcrumb_bar)
        self.breadcrumb_layout.setContentsMargins(10, 5, 12, 5)
        self.breadcrumb_layout.setSpacing(2)

        self.scan_progress_label = QLabel("")
        self.scan_progress_label.setFont(QFont("sans-serif", 10))
        self.scan_progress_label.setStyleSheet("color: #7a5020; padding: 0 10px;")
        self.scan_progress_label.setVisible(False)

        # 追加（＋）はツールバー左端（act_add）に移設済み。
        # ここは読み込み進捗ラベルのみ配置する。
        header_row.addWidget(self.scan_progress_label)
        header_row.addStretch()
        layout.addLayout(header_row)


        self.loading_label = QLabel(tr("loading"))
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setFont(QFont("sans-serif", 12))
        self.loading_label.setStyleSheet("color: #888; padding: 20px;")
        self.loading_label.setVisible(False)
        layout.addWidget(self.loading_label)

        self.list_view = WoodListView()
        self.list_view.setViewMode(QListView.IconMode)
        thumb_w = self.settings.get("thumbnail_width", 190)
        thumb_h = self.settings.get("thumbnail_height", 270)
        self.list_view.setIconSize(QSize(thumb_w, thumb_h))
        self.list_view.setSpacing(0)
        self.list_view.setResizeMode(QListView.Adjust)
        self.list_view.setWrapping(True)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setMovement(QListView.Static)
        self.list_view.setAcceptDrops(True)
        self.list_view.setDropIndicatorShown(True)
        self._delegate = BookshelfDelegate(self.list_view)
        self.list_view.setItemDelegate(self._delegate)

        sb_policy = Qt.ScrollBarAlwaysOn if self.settings["scrollbar_always"] else Qt.ScrollBarAsNeeded
        self.list_view.setVerticalScrollBarPolicy(sb_policy)

        # 初期スタイル（木目生成前のフォールバック色）
        self.list_view.setStyleSheet("""
            QListView {
                background-color: #eedead;
                border: 2px solid #8b6020;
                border-radius: 10px;
                color: #1a0e00;
            }
            QListView::item {
                background: transparent;
                border: none;
            }
            QListView::item:hover {
                background: transparent;
                border: none;
            }
            QListView::item:selected {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(180,130,70,80);
                width: 10px; border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: rgba(140,95,40,180);
                border-radius: 5px; min-height: 20px;
            }
        """)
        self.list_view.doubleClicked.connect(self.on_double_click)
        self.list_view.item_activated.connect(self.on_double_click)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.list_view)

        # パンくずバーを本棚の子にして左下フローティング表示にする
        self.breadcrumb_bar.setParent(self.list_view)
        self.breadcrumb_bar.raise_()
        self.list_view.overlay_reposition_cb = self._reposition_breadcrumb

        self.model = QStandardItemModel()
        self.list_view.setModel(self.model)

        # 選択状態変更時にアクションボタンを更新
        self.list_view.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_buttons()
        )
        # カレント項目が変わったら（マウス・キーボード両方）パンくずにその名前を表示
        self.list_view.selectionModel().currentChanged.connect(
            self._on_current_changed
        )

        # スクロール時に棚板位置を再描画
        self.list_view.verticalScrollBar().valueChanged.connect(
            lambda _: self.list_view.viewport().update()
        )

        # 下部: 検索バー（中央）+ アクションボタン（右）
        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 4, 6, 4)
        footer_row.setSpacing(6)

        # 左ストレッチ（検索を中央寄せにするため）
        footer_row.addStretch(1)

        # 検索ボックス（少し小さめ・IME対応）
        self.search_box = SearchLineEdit()
        self.search_box.setPlaceholderText(tr("search_placeholder"))
        self.search_box.setFixedHeight(28)
        self.search_box.setFixedWidth(280)
        self.search_box.setStyleSheet("""
            QLineEdit {
                background: rgba(255, 248, 225, 200);
                border: 1px solid #8b6020;
                border-radius: 14px;
                padding: 2px 12px;
                color: #2a1500;
                font-size: 10pt;
            }
            QLineEdit:focus {
                border: 2px solid #5a8a3c;
                background: rgba(255, 252, 235, 230);
            }
        """)
        self.search_box.search_requested.connect(self._start_search)
        footer_row.addWidget(self.search_box)


        # 検索クリアボタン（検索中のみ表示）
        self.search_clear_btn = QPushButton(tr("search_clear_btn"))
        self.search_clear_btn.setFixedHeight(28)
        self.search_clear_btn.setStyleSheet("""
            QPushButton {
                background: rgba(180, 100, 50, 180);
                color: white; border-radius: 6px;
                padding: 2px 10px; font-size: 9pt;
            }
            QPushButton:hover { background: rgba(160, 80, 30, 200); }
        """)
        self.search_clear_btn.clicked.connect(self._clear_search)
        self.search_clear_btn.setVisible(False)
        footer_row.addWidget(self.search_clear_btn)

        # ファイル数ラベル
        self.count_label = QLabel("")
        self.count_label.setFont(QFont("sans-serif", 9))
        self.count_label.setStyleSheet("color: #888; padding: 2px 6px;")
        footer_row.addWidget(self.count_label)

        # 右ストレッチ
        footer_row.addStretch(1)

        # 「本として開く」ボタン（フォルダ選択時のみ表示）
        self.btn_open_as_book = QPushButton(tr("btn_open_as_book"))
        self.btn_open_as_book.setFixedHeight(28)
        self.btn_open_as_book.setStyleSheet("""
            QPushButton {
                background: rgba(90, 138, 60, 200);
                color: white; border-radius: 6px;
                padding: 2px 12px; font-size: 10pt;
            }
            QPushButton:hover { background: rgba(70, 118, 40, 230); }
        """)
        self.btn_open_as_book.clicked.connect(self._open_folder_as_book)
        self.btn_open_as_book.setVisible(False)
        footer_row.addWidget(self.btn_open_as_book)

        # 「開く」ボタン
        self.btn_open = QPushButton(tr("btn_open"))
        self.btn_open.setFixedHeight(28)
        self.btn_open.setEnabled(False)
        self.btn_open.setStyleSheet("""
            QPushButton {
                background: rgba(140, 100, 50, 180);
                color: white; border-radius: 6px;
                padding: 2px 14px; font-size: 10pt;
            }
            QPushButton:hover { background: rgba(120, 80, 30, 210); }
            QPushButton:disabled {
                background: rgba(160, 140, 120, 100);
                color: rgba(255, 255, 255, 100);
            }
        """)
        self.btn_open.clicked.connect(self._open_selected_item)
        footer_row.addWidget(self.btn_open)

        layout.addLayout(footer_row)

        self._stack.addWidget(shelf_widget)

        self._inline_placeholder = QWidget()
        self._stack.addWidget(self._inline_placeholder)

    def create_toolbar(self):
        toolbar = QToolBar()
        toolbar.setIconSize(QSize(24, 24))
        toolbar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        toolbar.setContextMenuPolicy(Qt.PreventContextMenu)
        self.addToolBar(toolbar)
        self.toolbar = toolbar

        # 追加（＋）: ツールバー左端。ルート本棚でのみ表示する
        self.act_add = toolbar.addAction(toolbar_icon("add", "list-add"), tr("toolbar_add"))
        self.act_add.triggered.connect(self._show_add_menu)
        self.act_add.setToolTip(tr("add_btn_tip"))

        home = toolbar.addAction(toolbar_icon("home", "go-home"), tr("toolbar_home"))
        home.triggered.connect(self.go_home)
        home.setToolTip(tr("toolbar_home_tip"))

        self.act_up = toolbar.addAction(toolbar_icon("up", "go-up"), tr("toolbar_up"))
        self.act_up.triggered.connect(self.go_parent)
        self.act_up.setToolTip(tr("toolbar_up_tip"))

        refresh = toolbar.addAction(toolbar_icon("refresh", "view-refresh"), tr("toolbar_refresh"))
        refresh.triggered.connect(self._on_toolbar_refresh)
        refresh.setToolTip(tr("toolbar_refresh_tip"))

        history = toolbar.addAction(toolbar_icon("history", "document-open-recent"), tr("toolbar_history"))
        history.triggered.connect(self._show_history_menu)
        history.setToolTip(tr("toolbar_history_tip"))

        sort_act = toolbar.addAction(toolbar_icon("sort"), tr("toolbar_sort"))
        sort_act.triggered.connect(self._show_sort_menu)
        sort_act.setToolTip(tr("toolbar_sort_tip"))

        filter_act = toolbar.addAction(toolbar_icon("filter"), tr("toolbar_filter"))
        filter_act.triggered.connect(self._show_filter_menu)
        filter_act.setToolTip(tr("toolbar_filter_tip"))

        stats_act = toolbar.addAction(toolbar_icon("stats"), tr("toolbar_stats"))
        stats_act.triggered.connect(self._show_stats)
        stats_act.setToolTip(tr("toolbar_stats_tip"))

        zoom_act = toolbar.addAction(toolbar_icon("zoom"), tr("toolbar_zoom"))
        zoom_act.triggered.connect(self._cycle_thumbnail_size)
        zoom_act.setToolTip(tr("toolbar_zoom_tip"))

        self.act_back_to_shelf = toolbar.addAction(toolbar_icon("back", "go-previous"), tr("toolbar_back"))
        self.act_back_to_shelf.triggered.connect(self._back_to_shelf)
        self.act_back_to_shelf.setVisible(False)

        spacer = QWidget()
        spacer.setSizePolicy(SP.Expanding, SP.Preferred)
        toolbar.addWidget(spacer)

        help_btn = toolbar.addAction(toolbar_icon("help", "help-contents"), tr("toolbar_help"))
        help_btn.triggered.connect(self._show_help)
        help_btn.setToolTip(tr("toolbar_help_tip"))

        _icon_settings = toolbar_icon("settings", "preferences-system")
        if _icon_settings.isNull():
            _icon_settings = _make_gear_icon(int(toolbar.iconSize().width()))
        settings_btn = toolbar.addAction(_icon_settings, tr("toolbar_settings"))
        settings_btn.triggered.connect(self.open_settings)
        settings_btn.setToolTip(tr("toolbar_settings_tip"))

    def _show_help(self):
        """本棚モードのヘルプを表示"""
        from help_docs import show_help_dialog
        show_help_dialog(self, "shelf")

    def create_menubar(self):
        menubar = self.menuBar()
        menubar.setContextMenuPolicy(Qt.PreventContextMenu)
        file_menu = menubar.addMenu(tr("menu_file"))
        # スタイル未指定だとFusionスタイルの暗色背景で表示されるため木目調に合わせる
        file_menu.setStyleSheet("""
            QMenu {
                background: #faf5ee; border: 1px solid #8b5a2b;
                border-radius: 6px; padding: 4px;
            }
            QMenu::item { padding: 8px 24px; color: #1a1a1a; font-size: 13px; }
            QMenu::item:selected { background: #e8d8b8; border-radius: 4px; }
        """)
        act_folder = QAction(tr("menu_add_folder"), self)
        act_folder.triggered.connect(self.add_folder_dialog)
        file_menu.addAction(act_folder)
        act_file = QAction(tr("menu_add_file"), self)
        act_file.triggered.connect(self.add_file_dialog)
        file_menu.addAction(act_file)

    def _show_add_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #faf5ee; border: 1px solid #8b5a2b;
                border-radius: 6px; padding: 4px;
            }
            QMenu::item { padding: 8px 24px; color: #1a1a1a; font-size: 13px; }
            QMenu::item:selected { background: #e8d8b8; border-radius: 4px; }
        """)
        menu.addAction(toolbar_icon("folder_add", "folder-new"),  tr("menu_add_folder")).triggered.connect(self.add_folder_dialog)
        menu.addAction(toolbar_icon("file_add", "document-open"), tr("menu_add_file")).triggered.connect(self.add_file_dialog)
        # ツールバーの追加ボタン直下にメニューを出す
        w = self.toolbar.widgetForAction(self.act_add)
        if w is not None:
            menu.exec(w.mapToGlobal(w.rect().bottomLeft()))
        else:
            menu.exec(self.toolbar.mapToGlobal(self.toolbar.rect().bottomLeft()))

    # ------------------------------------------------------------------ #
    # 設定
    # ------------------------------------------------------------------ #

    def open_settings(self):
        old_thumb_w = self.settings.get("thumbnail_width", 190)
        old_thumb_h = self.settings.get("thumbnail_height", 270)
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec():
            self.settings = dlg.get_settings()
            size_changed = (
                self.settings.get("thumbnail_width", 190) != old_thumb_w
                or self.settings.get("thumbnail_height", 270) != old_thumb_h
            )
            self._apply_settings(rebuild=size_changed)

    def _apply_wood_theme(self, wood_path: str):
        """
        木目テクスチャを全ウィジェットに適用する。
        木目PNGが生成された後に呼ばれる。
        """
        p = wood_path.replace("\\", "/")
        self.setStyleSheet(f"""
            /* ウィンドウ本体・中央ウィジェット */
            QMainWindow, QWidget#qt_centralwidget {{
                background-image: url("{p}");
            }}

            /* ツールバー */
            QToolBar {{
                background-image: url("{p}");
                background-repeat: repeat;
                border-bottom: 2px solid rgba(120, 80, 30, 120);
                spacing: 6px;
                padding: 2px 6px;
            }}
            QToolButton {{
                background: transparent;
                color: #3a2000;
                border-radius: 5px;
                padding: 4px 8px;
                font-weight: bold;
            }}
            QToolButton:hover {{
                background: rgba(180, 130, 60, 100);
            }}
            QToolButton:pressed {{
                background: rgba(140, 95, 30, 150);
            }}

            /* メニューバー */
            QMenuBar {{
                background-image: url("{p}");
                background-repeat: repeat;
                color: #3a2000;
                border-bottom: 1px solid rgba(120, 80, 30, 80);
                font-weight: bold;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 4px 12px;
                border-radius: 4px;
            }}
            QMenuBar::item:selected {{
                background: rgba(180, 130, 60, 120);
            }}
            QMenu {{
                background-color: #f5e8c8;
                border: 1px solid #8b6020;
                border-radius: 6px;
                color: #2a1500;
            }}
            QMenu::item {{ padding: 6px 24px; }}
            QMenu::item:selected {{ background: rgba(180, 130, 60, 160); border-radius: 4px; }}

            /* 本棚エリア全体 */
            QWidget {{
                background-color: transparent;
                color: #2a1500;
            }}

            /* パスラベル */
            QLabel#path_label {{
                background: rgba(200, 160, 90, 160);
                border-radius: 6px;
                color: #1a0800;
                padding: 10px;
                font-weight: bold;
            }}

            /* ファイルパスラベル・カウントラベル */
            QLabel {{
                background: transparent;
                color: #3a2000;
            }}

            /* ローディングラベル */
            QLabel#loading_label {{
                color: rgba(80, 50, 10, 180);
            }}
        """)

        # path_label は objectName で個別設定
        self.path_label.setObjectName("path_label")
        self.path_label.setStyleSheet(
            "padding: 10px 14px; background: rgba(200,158,88,180);"
            "color: #1a0800; border-radius: 6px; font-weight: bold;"
        )
        self.count_label.setStyleSheet("color: #7a5020; padding: 2px 8px; background: transparent;")
        self.loading_label.setStyleSheet("color: rgba(80,50,10,180); padding: 20px; background: transparent;")

    def _apply_settings(self, rebuild: bool = True):
        sb_policy = Qt.ScrollBarAlwaysOn if self.settings["scrollbar_always"] else Qt.ScrollBarAsNeeded
        self.list_view.setVerticalScrollBarPolicy(sb_policy)
        # 「フォルダとファイル名を表示」トグルを即反映（パンくずの表示/非表示）
        self._update_breadcrumb()
        thumb_w = self.settings.get("thumbnail_width", 190)
        thumb_h = self.settings.get("thumbnail_height", 270)
        self.list_view.setIconSize(QSize(thumb_w, thumb_h))
        self.list_view._update_grid_size()

        if not rebuild:
            # サムネイルサイズ以外の変更はモデル再構築不要
            # サムネイル領域のレイアウトだけ更新（既存pixmapは再利用される）
            self.list_view.viewport().update()
            return

        # サムネイルサイズ変更時のみ再スキャン（スクロール位置は維持）
        current_path = self._get_current_scroll_path()
        if current_path:
            self._pending_back_scroll = current_path
            self.list_view.setVisible(False)
            self.loading_label.setVisible(False)
        self.refresh_view()

    # サムネイルクイック切替のプリセット（幅, 高さ）。おおむね 5:7 の書影比。
    THUMB_PRESETS = [(110, 154), (150, 210), (200, 280), (260, 364)]

    def _cycle_thumbnail_size(self):
        """ツールバーの「表示」ボタン: サムネイルサイズをプリセット間で素早く切り替える。
        重い再スキャンはせず、iconSize変更で即座に見た目を更新し、
        表示範囲のサムネイルだけ新サイズで再描画（ディスクキャッシュから高速）する。"""
        cur_w = self.settings.get("thumbnail_width", 150)
        # 現在サイズに最も近いプリセットの次を選ぶ
        idx = min(range(len(self.THUMB_PRESETS)),
                  key=lambda i: abs(self.THUMB_PRESETS[i][0] - cur_w))
        nxt = (idx + 1) % len(self.THUMB_PRESETS)
        w, h = self.THUMB_PRESETS[nxt]
        self.settings["thumbnail_width"] = w
        self.settings["thumbnail_height"] = h
        from settings import save_settings
        save_settings(self.settings)

        # 即時反映: iconSize・グリッドを更新（既存Pixmapはデリゲートがスケール）
        self.list_view.setIconSize(QSize(w, h))
        self.list_view._update_grid_size()
        # 表示中サムネイルを新サイズでクリアに再描画する
        for row in list(self._loaded_rows):
            item = self.model.item(row)
            if item:
                item.setData(None, PIXMAP_ROLE)
        self._loaded_rows.clear()
        self.list_view.viewport().update()
        QTimer.singleShot(0, self._load_window_thumbnails)
        # 手動配置の位置はセル幅が変わるので再適用
        if self.settings.get("shelf_sort") == "manual":
            QTimer.singleShot(30, self._apply_manual_layout)
        self.count_label.setText(tr("zoom_status", w=w, h=h))

    # ------------------------------------------------------------------ #
    # ライブラリ / 永続化
    # ------------------------------------------------------------------ #

    def load_library(self):
        if LIBRARY_DB.exists():
            try:
                return json.loads(LIBRARY_DB.read_text(encoding='utf-8'))
            except:
                return []
        return []

    def save_library(self):
        LIBRARY_DB.write_text(
            json.dumps(self.registered_items, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    def _read_last_loc_data(self) -> dict:
        if LAST_LOC_FILE.exists():
            try:
                return json.loads(LAST_LOC_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {}

    def _save_last_location(self):
        LAST_LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_last_loc_data()
        data["folder"] = self.current_folder
        LAST_LOC_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _save_last_book(self, file_path: Path):
        LAST_LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_last_loc_data()
        data["last_book"] = str(file_path)
        # ビューアを開いた時点のフォルダを保存（本棚に戻る際に使用）
        data["last_book_folder"] = self.current_folder
        LAST_LOC_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    # ------------------------------------------------------------------ #
    # 閲覧履歴
    # ------------------------------------------------------------------ #

    def _load_history(self) -> list:
        """閲覧履歴を読む。[{path, opened_at}] の新しい順リスト。"""
        if HISTORY_FILE.exists():
            try:
                data = json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        return []

    def _add_history(self, path: Path):
        """閲覧履歴の先頭に追加する（重複は先頭へ移動、最大HISTORY_MAX件）"""
        from datetime import datetime
        path_str = str(path)
        entries = [e for e in self._load_history() if e.get("path") != path_str]
        entries.insert(0, {
            "path": path_str,
            "opened_at": datetime.now().isoformat(timespec="seconds"),
        })
        del entries[HISTORY_MAX:]
        try:
            HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_FILE.write_text(
                json.dumps(entries, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f"履歴保存エラー: {e}")

    # ------------------------------------------------------------------ #
    # 手動配置（並び順=手動 のとき、アイテムを段へ自由配置）
    # ------------------------------------------------------------------ #

    def _view_key(self) -> str:
        """手動レイアウトの保存キー（ルート or フォルダパス）"""
        return "ROOT" if self.current_folder is None else str(self.current_folder)

    def _load_shelf_layout(self) -> dict:
        """shelf_layout.json をメモリキャッシュ付きで読む。"""
        if self._shelf_layout_cache is not None:
            return self._shelf_layout_cache
        if SHELF_LAYOUT_FILE.exists():
            try:
                self._shelf_layout_cache = json.loads(SHELF_LAYOUT_FILE.read_text(encoding='utf-8'))
            except Exception:
                self._shelf_layout_cache = {}
        else:
            self._shelf_layout_cache = {}
        return self._shelf_layout_cache

    def _on_manual_layout_changed(self):
        """手動配置で並びが変わった → 現在の全アイテムの(段,列)を保存する。
        一部だけ保存すると次回再構築時に未保存アイテムがずれるため、
        現在の見た目の並びをそのまま丸ごと記録して決定的にする。"""
        cols = max(1, self.list_view._manual_cols)
        positions = {}
        for r in range(self.model.rowCount()):
            item = self.model.item(r)
            if item is None:
                continue
            path_str = item.data(Qt.UserRole)
            if not path_str:   # プレースホルダー（空席）は保存しない
                continue
            row, col = divmod(r, cols)
            positions[path_str] = [row, col]
        layout = self._load_shelf_layout()
        layout[self._view_key()] = positions
        try:
            SHELF_LAYOUT_FILE.write_text(
                json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"レイアウト保存エラー: {e}")

    def _clear_manual_layout(self):
        """現在の表示（ルート or フォルダ）の手動配置を破棄する"""
        layout = self._load_shelf_layout()
        if self._view_key() in layout:
            del layout[self._view_key()]
            try:
                SHELF_LAYOUT_FILE.write_text(
                    json.dumps(layout, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception as e:
                print(f"レイアウト保存エラー: {e}")

    def _current_manual_cols(self) -> int:
        """現在のビューポート幅から表示列数を算出する（手動配置の配列構築に使う）"""
        vp_w = self.list_view.viewport().width()
        natural_w = self.list_view.sizeHintForColumn(0)
        if natural_w <= 0:
            natural_w = self.list_view.iconSize().width() + 4
        if vp_w <= 0 or natural_w <= 0:
            return 1
        return max(1, vp_w // natural_w)

    # 手動配置で末尾に確保する空席の段数（空の本棚へドロップできるようにするため）
    MANUAL_TRAILING_ROWS = 4

    def _build_manual_sequence(self, items: list) -> list:
        """手動配置モード用に、保存済み(段,列)へアイテムを配置し、
        空いている段はプレースホルダー（None）で埋めた表示順リストを作る。
        末尾にも空席の段を確保して「何もない本棚の場所」へドロップできるようにする。
        Movement は常に Static のままなので、この「モデル行の並び順」だけで
        位置を表現する（Qtの実績あるグリッド自動整列をそのまま利用できる）。
        """
        cols = self._current_manual_cols()
        self.list_view._manual_cols = cols
        saved = self._load_shelf_layout().get(self._view_key(), {})

        placed: dict[int, tuple] = {}
        unplaced = []
        for path, is_dir in items:
            pos = saved.get(path) if saved else None
            if pos and isinstance(pos, list) and len(pos) == 2:
                idx = int(pos[0]) * cols + int(pos[1])
                if idx >= 0 and idx not in placed:
                    placed[idx] = (path, is_dir)
                    continue
            unplaced.append((path, is_dir))

        # 保存済み位置とアイテム数から必要な長さを決め、末尾に空席行を追加する
        max_placed = (max(placed.keys()) + 1) if placed else 0
        content_len = max(max_placed, len(items))
        # 現在のアイテムがちょうど埋まる段の次から、さらに数段ぶん空席を足す
        rows_used = (content_len + cols - 1) // cols
        seq_len = (rows_used + self.MANUAL_TRAILING_ROWS) * cols

        seq: list = [None] * seq_len
        for idx, entry in placed.items():
            if idx < seq_len:
                seq[idx] = entry

        gap_indices = [i for i, v in enumerate(seq) if v is None]
        gi = 0
        for entry in unplaced:
            if gi < len(gap_indices):
                seq[gap_indices[gi]] = entry
                gi += 1
            else:
                seq.append(entry)
        return seq

    def _wood_menu(self) -> QMenu:
        """木目テーマの共通スタイルを適用したQMenuを返す"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #faf5ee; border: 1px solid #8b5a2b;
                border-radius: 6px; padding: 4px;
            }
            QMenu::item { padding: 8px 24px; color: #1a1a1a; font-size: 13px; }
            QMenu::item:selected { background: #e8d8b8; border-radius: 4px; }
            QMenu::separator { height: 1px; background: #d9c49a; margin: 4px 8px; }
        """)
        return menu

    def _show_sort_menu(self):
        """並び順メニュー（チェック付き）＋シリーズまとめトグル"""
        menu = self._wood_menu()
        cur = self.settings.get("shelf_sort", "name")
        for mode, label_key in (("name", "sort_name"),
                                ("added", "sort_added"),
                                ("recent", "sort_recent"),
                                ("manual", "sort_manual")):
            act = menu.addAction(("✓ " if cur == mode else "　 ") + tr(label_key))
            act.setData(mode)
        menu.addSeparator()
        grouping = self.settings.get("series_grouping", False)
        act_series = menu.addAction(("✓ " if grouping else "　 ") + tr("sort_series_group"))
        act_series.setData("__series__")

        # 手動配置モード中のみ「手動配置をリセットして名前順に戻す」を表示
        if cur == "manual":
            menu.addSeparator()
            act_reset = menu.addAction("　 " + tr("sort_manual_reset"))
            act_reset.setData("__reset_manual__")

        chosen = menu.exec(self.mapToGlobal(self.rect().topLeft()) + QPoint(200, 80))
        if chosen is None:
            return
        from settings import save_settings
        data = chosen.data()
        if data == "__series__":
            self.settings["series_grouping"] = not grouping
        elif data == "__reset_manual__":
            # この本棚の手動配置だけを破棄する（並び順モードは手動のまま維持）。
            # 手動モードで配置データが無い本棚は名前順で表示されるため、
            # この本棚だけが名前順に戻り、他の本棚の手動配置は保持される。
            self._clear_manual_layout()
            save_settings(self.settings)
            self.refresh_view()
            return
        else:
            self.settings["shelf_sort"] = data
        save_settings(self.settings)
        self.list_view.set_manual_mode(self.settings.get("shelf_sort") == "manual")
        self.refresh_view()

    def _show_filter_menu(self):
        """既読/未読フィルターメニュー"""
        menu = self._wood_menu()
        cur = self.settings.get("read_filter", "all")
        for mode, label_key in (("all", "filter_all"),
                                ("unread", "filter_unread"),
                                ("reading", "filter_reading"),
                                ("done", "filter_done")):
            act = menu.addAction(("✓ " if cur == mode else "　 ") + tr(label_key))
            act.setData(mode)
        chosen = menu.exec(self.mapToGlobal(self.rect().topLeft()) + QPoint(240, 80))
        if chosen is None:
            return
        from settings import save_settings
        self.settings["read_filter"] = chosen.data()
        save_settings(self.settings)
        self.refresh_view()

    def _show_stats(self):
        """読書統計ダイアログ"""
        from viewer import load_progress
        from page_cache import get_cached_names
        from datetime import datetime, timedelta

        prog = load_progress()
        reading = done = bookmarks = 0
        for ent in prog.values():
            if not isinstance(ent, dict):
                continue
            bookmarks += len(ent.get("bookmarks", {}) or {})
            page = ent.get("page", 0)
            if page and page > 0:
                total = 0
                p = ent.get("path")
                if p:
                    names = get_cached_names(Path(p))
                    total = len(names) if names else 0
                if total > 0 and page >= total - 1:
                    done += 1
                else:
                    reading += 1

        hist = self._load_history()
        now = datetime.now()
        def _within(e, days):
            try:
                return now - datetime.fromisoformat(e.get("opened_at", "")) <= timedelta(days=days)
            except Exception:
                return False
        opened_7d = sum(1 for e in hist if _within(e, 7))
        opened_30d = sum(1 for e in hist if _within(e, 30))

        from PySide6.QtWidgets import QDialog, QVBoxLayout, QGridLayout, QPushButton, QHBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("stats_title"))
        dlg.setMinimumWidth(340)
        dlg.setStyleSheet("QDialog { background: #faf5ee; }")
        layout = QVBoxLayout(dlg)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(8)
        rows = [
            (tr("stats_registered"), len(self.registered_items)),
            (tr("stats_reading"),    reading),
            (tr("stats_done"),       done),
            (tr("stats_bookmarks"),  bookmarks),
            (tr("stats_7d"),         opened_7d),
            (tr("stats_30d"),        opened_30d),
        ]
        for r, (label, value) in enumerate(rows):
            lab = QLabel(label)
            lab.setStyleSheet("color: #3a2000; font-size: 11pt;")
            val = QLabel(str(value))
            val.setStyleSheet("color: #1a1a1a; font-size: 13pt; font-weight: bold;")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(lab, r, 0)
            grid.addWidget(val, r, 1)
        layout.addLayout(grid)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn = QPushButton(tr("help_close"))
        btn.setStyleSheet("""
            QPushButton { background: #5a8a3c; color: white; border-radius: 6px;
                          padding: 8px 24px; font-weight: bold; }
            QPushButton:hover { background: #4a7a2c; }
        """)
        btn.clicked.connect(dlg.accept)
        btn_row.addWidget(btn)
        layout.addLayout(btn_row)
        dlg.exec()

    def _apply_shelf_transforms(self, items: list) -> list:
        """並び順・既読フィルター・シリーズグループ化を items に適用する。
        シリーズ内表示中は素通しする。"""
        self._series_groups = {}
        if self._series_view:
            return items
        s = self.settings

        # (path_str, is_dir) 形式に正規化
        norm = []
        for it in items:
            if isinstance(it, tuple):
                norm.append(it)
            else:
                norm.append((it, not bool(Path(it).suffix)))

        # 既読フィルター（ファイルのみ対象。フォルダは常に表示）
        flt = s.get("read_filter", "all")
        if flt != "all":
            from viewer import load_progress, _progress_key
            from page_cache import get_cached_names
            prog = load_progress()

            def _status(path_str: str) -> str:
                p = Path(path_str)
                saved = prog.get(_progress_key(p), {}).get("page", 0)
                if not saved or saved <= 0:
                    return "unread"
                names = get_cached_names(p)
                total = len(names) if names else 0
                if total > 0 and saved >= total - 1:
                    return "done"
                return "reading"

            norm = [(p, d) for p, d in norm if d or _status(p) == flt]

        # 並び順（フォルダ先頭は共通）
        from utils import natural_sort_key
        sort_mode = s.get("shelf_sort", "name")
        if sort_mode in ("name", "manual"):
            # 手動モードの基準順も名前順（未配置アイテムの並び・空き段埋めに使う）
            norm.sort(key=lambda t: (not t[1], natural_sort_key(Path(t[0]).name)))
        elif sort_mode == "added":
            if self.current_folder is not None:
                # フォルダ内は更新日時の新しい順（ルートは登録順を維持）
                def _mtime(p):
                    try:
                        return Path(p).stat().st_mtime
                    except Exception:
                        return 0
                norm.sort(key=lambda t: (not t[1], -_mtime(t[0])))
        elif sort_mode == "recent":
            hist_order = {e.get("path"): i for i, e in enumerate(self._load_history())}
            norm.sort(key=lambda t: (not t[1],
                                     hist_order.get(t[0], 10 ** 9),
                                     natural_sort_key(Path(t[0]).name)))

        # シリーズ自動グループ化（同名巻数違いを代表1件にまとめる）
        if s.get("series_grouping", False):
            from utils import series_key
            groups: dict[str, list] = {}
            for p, d in norm:
                if d:
                    continue
                k = series_key(Path(p).stem) or Path(p).stem.lower()
                groups.setdefault(k, []).append(p)
            result = []
            seen = set()
            for p, d in norm:
                if d:
                    result.append((p, d))
                    continue
                k = series_key(Path(p).stem) or Path(p).stem.lower()
                members = groups.get(k, [])
                if len(members) >= 2:
                    if k in seen:
                        continue
                    seen.add(k)
                    members = sorted(members, key=lambda x: natural_sort_key(Path(x).name))
                    self._series_groups[members[0]] = members
                    result.append((members[0], False))
                else:
                    result.append((p, d))
            norm = result

        # 手動配置モード: 保存済み(段,列)へ配置し、空き段はプレースホルダーで埋める
        if sort_mode == "manual":
            norm = self._build_manual_sequence(norm)

        return norm

    def _open_series(self, title: str, members: list):
        """シリーズグループの中身を一覧表示する（疑似フォルダ）"""
        self._series_view = (title, list(members))
        self._view_generation += 1
        self._stop_scan_worker()
        self._stop_thumbnail_worker()
        self._item_map = {}
        self._pixmap_lru.clear()
        self._loaded_rows.clear()
        self.path_label.setText(title if self.settings["show_hierarchy"] else "")
        self._update_breadcrumb(series_title=title)
        self._on_scan_done([(p, False) for p in members], self._view_generation)

    def _show_history_menu(self):
        """ツールバーの履歴ボタンから最近読んだ本のメニューを表示する"""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #faf5ee; border: 1px solid #8b5a2b;
                border-radius: 6px; padding: 4px;
            }
            QMenu::item { padding: 6px 24px; color: #1a1a1a; font-size: 13px; }
            QMenu::item:selected { background: #e8d8b8; border-radius: 4px; }
            QMenu::item:disabled { color: #a09888; }
        """)
        entries = self._load_history()
        if not entries:
            act = menu.addAction(tr("history_empty"))
            act.setEnabled(False)
        else:
            for e in entries:
                p = Path(e.get("path", ""))
                act = menu.addAction(p.name)
                if p.exists():
                    act.triggered.connect(
                        lambda checked=False, fp=p: self._open_viewer(fp)
                    )
                else:
                    act.setEnabled(False)  # 消えたファイルはグレー表示
        menu.exec(QCursor.pos())

    def _show_after_restore(self):
        """スクロール復元が完了してからウィンドウを表示する"""
        if not self.isVisible():
            self._show_with_state()

    def _show_with_state(self):
        """最大化・フルスクリーン状態を適用してウィンドウを表示する"""
        if getattr(self, '_pending_fullscreen', False):
            self.showFullScreen()
        elif getattr(self, '_pending_maximized', False):
            self.showMaximized()
        else:
            self.show()

    def _restore_and_refresh(self):
        """起動時: まずルート本棚を表示し、last_bookの存在チェックは
        バックグラウンドで行う（ネットワークドライブのスピンアップで
        UIがフリーズしないようにするため）"""
        if not self.settings.get("remember_last_location", True):
            self.refresh_view()
            return

        # 即座にルート本棚を表示（exists()チェックを待たない）
        self.current_folder = None
        self.refresh_view()

        # exists()チェックはバックグラウンドで実行
        data = self._read_last_loc_data()
        last_book = data.get("last_book")
        last_book_folder = data.get("last_book_folder")
        folder = data.get("folder")

        if not (last_book or folder):
            return

        worker = StartupCheckWorker(last_book, last_book_folder, folder)
        thread = QThread()
        worker.done.connect(self._on_startup_check_done)
        worker.done.connect(lambda _r: thread.quit())
        thread.started.connect(worker.run)
        worker.moveToThread(thread)
        self._startup_worker = worker
        self._startup_thread = thread
        thread.start()

    def _on_startup_check_done(self, result: dict):
        """起動時の存在チェック完了（メインスレッド）"""
        last_book = result.get("last_book")
        last_book_folder = result.get("last_book_folder")
        folder = result.get("folder")

        if last_book:
            # last_bookが存在する → ビューアを開く
            if last_book_folder:
                self.current_folder = last_book_folder
            else:
                self.current_folder = None
            # 起動時にルート本棚スキャンが先に完了していると _item_map に
            # ルートアイテムが残り、本棚に戻ったとき誤ったフォルダを表示する。
            # ビューアを開く前にクリアして refresh_view() が必ず走るようにする。
            self.model.clear()
            self._item_map = {}
            self._viewer_file_path = last_book
            self._open_viewer(Path(last_book))
        elif folder and folder != self.current_folder:
            # last_bookはないがfolderが存在する → そのフォルダを表示
            self.current_folder = folder
            self.refresh_view()
        # どちらも無効ならルート本棚のまま（既に表示済み）
    # ------------------------------------------------------------------ #
    # ファイル追加
    # ------------------------------------------------------------------ #

    def add_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, tr("add_folder_dlg_title"), "")
        if not folder:
            return
        path_str = str(Path(folder).resolve())
        if path_str not in self.registered_items:
            self.registered_items.append(path_str)
            self.save_library()
            self.refresh_view()
            _info_msg(self, tr("add_folder_ok_title"), tr("add_folder_ok_text", path=path_str))
        else:
            _info_msg(self, tr("add_folder_dup_title"), tr("add_folder_dup_text"))

    def add_file_dialog(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, tr("add_file_dlg_title"), "",
            tr("add_file_filter")
        )
        added = 0
        for f in files:
            path_str = str(Path(f).resolve())
            if path_str not in self.registered_items:
                self.registered_items.append(path_str)
                added += 1
        if added > 0:
            self.save_library()
            self.refresh_view()
            _info_msg(self, tr("add_file_ok_title"), tr("add_file_ok_text", n=added))

    def _on_files_dropped(self, paths: list):
        """エクスプローラー等からドロップされたフォルダ/ファイルを本棚に登録する"""
        added = 0
        for p_str in paths:
            p = Path(p_str)
            if not p.exists():
                continue
            # フォルダ、または対応拡張子のファイルのみ登録
            if not p.is_dir() and p.suffix.lower() not in SUPPORTED_EXTS:
                continue
            resolved = str(p.resolve())
            if resolved not in self.registered_items:
                self.registered_items.append(resolved)
                added += 1
        if added > 0:
            self.save_library()
            # ルート本棚表示中なら即時反映（フォルダ内ブラウズ中は次回ホームで反映）
            if self.current_folder is None:
                self.refresh_view()
            _info_msg(self, tr("drop_ok_title"), tr("drop_ok_text", n=added))

    # ------------------------------------------------------------------ #
    # 検索
    # ------------------------------------------------------------------ #


    def _start_search(self):
        query = self.search_box.text().strip()
        if not query:
            self._clear_search()
            return

        roots = [self.current_folder] if self.current_folder else list(self.registered_items)

        self._stop_search_worker()
        self._view_generation += 1
        current_gen = self._view_generation
        self._is_searching = True
        self.search_clear_btn.setVisible(True)

        self.model.clear()
        self._item_map = {}
        self._pixmap_lru.clear()
        self._loaded_rows.clear()
        self.loading_label.setText(tr("searching", query=query))
        self.loading_label.setVisible(True)
        self.list_view.setVisible(False)

        worker = SearchWorker(roots, query, current_gen)
        thread = QThread()
        # シグナル接続はmoveToThread前に行う
        worker.result_ready.connect(self._on_search_done)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        worker.moveToThread(thread)
        self._search_worker = worker
        self._search_thread = thread
        thread.start()

    def _on_search_done(self, matched: list[str], generation: int):
        if generation != self._view_generation:
            return
        self.loading_label.setVisible(False)
        self.list_view.setVisible(True)
        self.loading_label.setText(tr("loading"))

        thumb_w = self.settings.get("thumbnail_width", 190)
        thumb_h = self.settings.get("thumbnail_height", 270)
        from utils import folder_has_bracket_pattern
        use_bracket_rule = folder_has_bracket_pattern(
            Path(self.current_folder).name if self.current_folder else ""
        )

        _icon_folder = folder_icon()
        _icon_file = image_file_icon()

        file_paths = []
        all_qitems = []
        for path_str in sorted(matched):
            path = Path(path_str)
            is_dir = not bool(path.suffix)  # suffixで判定（is_dir()不要）
            if is_dir:
                display_name = path.name or str(path).rstrip('/\\')
            else:
                parsed = parse_filename(path.name, use_bracket_rule=use_bracket_rule)
                display_name = parsed.get("title") or path.stem

            qitem = QStandardItem()
            qitem.setText("")
            qitem.setData(display_name, TITLE_ROLE)
            qitem.setData(path_str, Qt.UserRole)
            qitem.setData(is_dir, IS_DIR_ROLE)

            if is_dir:
                qitem.setIcon(_icon_folder)
            else:
                qitem.setIcon(_icon_file)
                file_paths.append(path_str)
                self._item_map[path_str] = qitem

            all_qitems.append(qitem)

        if all_qitems:
            self.model.invisibleRootItem().appendRows(all_qitems)

        self.count_label.setText(tr("search_results", n=len(matched)))
        if file_paths:
            QTimer.singleShot(50, self._load_window_thumbnails)

    def _clear_search(self):
        self._stop_search_worker()
        self._is_searching = False
        self.search_box.clear()
        self.search_clear_btn.setVisible(False)
        self.refresh_view()

    def _stop_search_worker(self):
        if self._search_worker:
            self._search_worker.stop()
            try:
                self._search_worker.result_ready.disconnect()
            except RuntimeError:
                pass
        self._search_worker = None
        self._search_thread = None

    # ------------------------------------------------------------------ #
    # 表示更新（ディレクトリ列挙・サムネイル 完全非同期）
    # ------------------------------------------------------------------ #

    def _on_toolbar_refresh(self):
        """ツールバーの更新ボタン専用。
        .noimg マーカー（サムネイル生成失敗の記録）を削除してから再スキャンする。
        7-Zip インストール後などにボタンを押すと失敗済みサムネイルが再生成される。
        """
        try:
            from core import CACHE_ROOT
            for noimg in CACHE_ROOT.glob("*.noimg"):
                noimg.unlink(missing_ok=True)
                jpg = noimg.with_suffix('.jpg')
                if jpg.exists():
                    jpg.unlink(missing_ok=True)
        except Exception:
            pass
        self.refresh_view()

    def refresh_view(self):
        # シリーズ内表示は通常表示に戻す（_open_series はここを通らない）
        self._series_view = None
        # フォルダ移動時は選択アイテム名のパンくずをクリアする
        self._selected_crumb = None
        # ① 世代番号を進める（古いワーカーの結果を無視するため）
        self._view_generation += 1
        current_gen = self._view_generation

        # ② 実行中のワーカーを安全に停止してから新しいワーカーを起動する
        self._stop_scan_worker()
        self._stop_thumbnail_worker()

        # model.clear()はしない（_on_scan_doneで新データ構築後に切り替える）
        self._item_map: dict[str, QStandardItem] = {}
        self._pixmap_lru.clear()
        self._loaded_rows.clear()

        is_root = (self.current_folder is None)
        self.act_add.setVisible(is_root)

        label = (tr("shelf_top", n=len(self.registered_items)) if is_root
                 else tr("shelf_folder", folder=self.current_folder))
        self.path_label.setText(label if self.settings["show_hierarchy"] else "")
        self._update_breadcrumb()

        self.scan_progress_label.setText(tr("loading"))
        self.scan_progress_label.setVisible(True)
        self.loading_label.setVisible(False)

        # ③ スキャンワーカー起動
        worker = DirScanWorker(self.current_folder, list(self.registered_items), current_gen)
        thread = QThread()
        # シグナル接続はmoveToThread前に行う
        worker.scan_done.connect(self._on_scan_done)
        worker.scan_done.connect(lambda _items, _gen: thread.quit())
        worker.progress.connect(self._on_scan_progress)
        thread.started.connect(worker.run)
        worker.moveToThread(thread)
        # deleteLaterを使わない

        self._scan_worker = worker
        self._scan_thread = thread
        thread.start()

    def _stop_scan_worker(self):
        """スキャンスレッドをシグナル切断 → quit → wait で安全停止"""
        if self._scan_worker:
            try:
                self._scan_worker.scan_done.disconnect()
            except RuntimeError:
                pass
        try:
            stop_thread_safely(self._scan_thread)
        except RuntimeError:
            pass
        self._scan_worker = None
        self._scan_thread = None

    def _stop_thumbnail_worker(self):
        """サムネイルスレッドをフラグ → シグナル切断 → quit → wait で安全停止"""
        if self._thumb_worker:
            self._thumb_worker.stop()
            try:
                self._thumb_worker.thumbnails_batch.disconnect()
            except RuntimeError:
                pass
        try:
            # キャッシュなし2000ファイルの場合でもrun()がcancel_futures=Trueで即帰るため
            # 既実行中ワーカー(最大8)の1枚分待ちで済む。余裕を持って10秒に設定
            stop_thread_safely(self._thumb_thread, timeout_ms=10000)
        except RuntimeError:
            pass
        self._thumb_worker = None
        self._thumb_thread = None

    def _soft_stop_thumbnail_worker(self):
        """スクロール用ノンブロッキング停止: シグナルを切断して停止フラグを立てるだけ。
        スレッドの終了は待たず、_zombie_threads で生存を保証して自然終了させる。"""
        if self._thumb_worker:
            self._thumb_worker.stop()
            try:
                self._thumb_worker.thumbnails_batch.disconnect()
            except RuntimeError:
                pass
            self._thumb_worker = None
        if self._thumb_thread:
            thread = self._thumb_thread
            self._thumb_thread = None
            if thread.isRunning():
                thread.quit()
                self._zombie_threads.append(thread)
                def _cleanup(t=thread):
                    try:
                        self._zombie_threads.remove(t)
                    except ValueError:
                        pass
                thread.finished.connect(_cleanup)

    def _on_scan_progress(self, done: int, total: int, generation: int):
        if generation != self._view_generation:
            return
        if total > 0:
            pct = int(done / total * 100)
            self.scan_progress_label.setText(tr("loading_pct", pct=pct))
        else:
            self.scan_progress_label.setText(tr("loading"))

    def _on_scan_done(self, items_to_show: list, generation: int):
        """スキャン完了コールバック（メインスレッドで実行）"""
        if generation != self._view_generation:
            return

        # 並び順・フィルター・シリーズグループ化を適用
        items_to_show = self._apply_shelf_transforms(items_to_show)

        self.scan_progress_label.setVisible(False)
        self.loading_label.setVisible(False)
        # 新データが揃ったのでここで切り替える（古い表示が一瞬消える問題を回避）
        self.model.clear()
        # _pending_back_scrollがある場合はアイテム構築後にスクロールしてから表示
        pending = getattr(self, '_pending_back_scroll', None)
        if not pending:
            self.list_view.setVisible(True)

        thumb_w = self.settings.get("thumbnail_width", 190)
        thumb_h = self.settings.get("thumbnail_height", 270)

        from utils import folder_has_bracket_pattern
        current_folder_name = Path(self.current_folder).name if self.current_folder else ""
        use_bracket_rule = folder_has_bracket_pattern(current_folder_name)

        # アイコンをループ外で1回だけ取得する。
        # Windows では standardIcon() が毎回リソースを検索するため
        # 2000回ループ内で呼ぶと数秒のブロックが発生し「応答なし」になる。
        _icon_folder = folder_icon()
        _icon_file = image_file_icon()

        file_paths = []
        file_count = 0
        all_qitems = []  # 一括挿入用バッファ

        for item in items_to_show:
            # None = 手動配置モードの空き段（プレースホルダー行）
            if item is None:
                placeholder = QStandardItem()
                placeholder.setText("")
                placeholder.setData(True, PLACEHOLDER_ROLE)
                # ドロップは受け付けるが選択・クリック・ドラッグは不可にする
                placeholder.setFlags(Qt.ItemIsDropEnabled)
                all_qitems.append(placeholder)
                continue
            # DirScanWorkerが (path_str, is_dir) タプルを返す
            if isinstance(item, tuple):
                path_str, is_dir = item
            else:
                # 旧形式との互換（文字列の場合はsuffixで判定）
                path_str = item
                is_dir = not bool(Path(path_str).suffix)

            path = Path(path_str)

            # フォルダ以外は対応拡張子のみ表示（is_dir判定済みなのでpath.is_dir()不要）
            if not is_dir and path.suffix.lower() not in SUPPORTED_EXTS:
                continue

            # 表示名を決定（パス文字列操作のみ・ネットワークアクセスなし）
            if is_dir:
                display_name = path.name or str(path).rstrip('/\\')
            else:
                parsed = parse_filename(path.name, use_bracket_rule=use_bracket_rule)
                display_name = parsed.get("title") or path.stem
                file_count += 1

            qitem = QStandardItem()
            qitem.setText("")
            qitem.setData(display_name, TITLE_ROLE)
            qitem.setData(path_str, Qt.UserRole)
            qitem.setData(is_dir, IS_DIR_ROLE)
            qitem.setToolTip("")

            if is_dir:
                qitem.setIcon(_icon_folder)
            else:
                qitem.setIcon(_icon_file)
                file_paths.append(path_str)
                # シリーズ代表アイテム: 構成リストと「（全N冊）」表示を設定
                members = self._series_groups.get(path_str)
                if members:
                    from utils import series_display_title
                    qitem.setData(list(members), SERIES_ROLE)
                    qitem.setData(
                        tr("series_label",
                           title=series_display_title(display_name), n=len(members)),
                        TITLE_ROLE)
            # フォルダ含む全アイテムを登録（スクロール位置復元に使用）
            self._item_map[path_str] = qitem
            all_qitems.append(qitem)

        # appendRow を N 回呼ぶと N 回 rowsInserted が発火してUIが固まる。
        # appendRows で一括挿入すれば rowsInserted は1回だけ。
        if all_qitems:
            self.model.invisibleRootItem().appendRows(all_qitems)

        self.count_label.setText(tr("file_count", n=file_count) if file_count > 0 else "")

        # _pending_back_scrollがある場合はスクロール復元後にlist_viewを表示
        pending = getattr(self, '_pending_back_scroll', None)
        if pending:
            self._back_to_shelf_show()

        if file_paths:
            # ビューのレイアウト確定後にウィンドウ読み込みを開始
            QTimer.singleShot(50, self._load_window_thumbnails)

    def _start_thumbnail_worker(self, paths: list[str], generation: int):
        thumb_size = (
            self.settings.get("thumbnail_width", 190),
            self.settings.get("thumbnail_height", 270),
        )
        worker = ThumbnailWorker(paths, generation, thumb_size)
        thread = QThread()
        # シグナル接続はmoveToThread前に行う
        worker.thumbnails_batch.connect(self._on_thumbnails_batch)
        worker.finished.connect(thread.quit)
        thread.started.connect(worker.run)
        worker.moveToThread(thread)

        self._thumb_worker = worker
        self._thumb_thread = thread
        thread.start()

    def _on_thumbnails_batch(self, batch: list, generation: int):
        if generation != self._view_generation:
            return
        from page_cache import get_cached_pages as _gcp
        from viewer import load_progress, _progress_key
        from page_cache import get_cached_names as _gcn
        _progress = load_progress()
        for path_str, pixmap in batch:
            item = self._item_map.get(path_str)
            if item:
                self._register_pixmap(path_str, item, pixmap)
                p = Path(path_str)
                if p.suffix.lower() in ('.zip', '.cbz', '.rar', '.cbr', '.7z', '.cb7', '.pdf'):
                    # キャッシュ済みフラグ
                    item.setData(_gcp(p) is not None, CACHED_ROLE)
                    # しおり状態（_progressを使い回してファイルI/Oを1回に抑える）
                    saved = _progress.get(_progress_key(p), {}).get("page", 0)
                    if saved > 0:
                        # 総ページ数をキャッシュメタから取得
                        names = _gcn(p)
                        total = len(names) if names else 0
                        if total > 0 and saved >= total - 1:
                            item.setData('done', PROGRESS_ROLE)
                        else:
                            item.setData('reading', PROGRESS_ROLE)

    _PIXMAP_MAX = 400   # RAMに保持するPixmap最大件数（400件 × ~200KB ≈ 80MB）

    def _register_pixmap(self, path_str: str, item, pixmap: QPixmap):
        """Pixmapをモデルに登録して _loaded_rows を更新する。"""
        item.setData(pixmap, PIXMAP_ROLE)
        idx = self.model.indexFromItem(item)
        if idx.isValid():
            self._loaded_rows.add(idx.row())
        self._pixmap_lru[path_str] = item   # 後方互換のため保持

    THUMB_HALF_WINDOW = 50  # 画面中央から前後この件数のPixmapだけ保持

    def _load_window_thumbnails(self):
        """現在のスクロール位置を中心に ±THUMB_HALF_WINDOW 件だけPixmapをロード。
        範囲外はPixmap解放、範囲内で未ロードのものはThumbnailWorkerで取得する。"""
        if self.model.rowCount() == 0 or self._view_generation == 0:
            return

        # --- 中心モデル行を算出 ---
        item_h = self.list_view.sizeHintForRow(0)
        item_w = self.list_view.sizeHintForColumn(0)
        vp_w   = self.list_view.viewport().width()
        vp_h   = self.list_view.viewport().height()
        scroll_y = self.list_view.verticalScrollBar().value()

        if item_h > 0 and item_w > 0 and vp_w > 0:
            cols = max(1, vp_w // item_w)
            center_vrow = (scroll_y + vp_h // 2) // item_h
            center_row  = center_vrow * cols + cols // 2
        else:
            center_row = 0

        total = self.model.rowCount()
        lo = max(0, center_row - self.THUMB_HALF_WINDOW)
        hi = min(total - 1, center_row + self.THUMB_HALF_WINDOW)
        window = set(range(lo, hi + 1))

        # --- 範囲外のPixmapを解放 ---
        for row in list(self._loaded_rows - window):
            item = self.model.item(row)
            if item:
                item.setData(None, PIXMAP_ROLE)
            self._loaded_rows.discard(row)

        # --- 範囲内で未ロードのパスを収集 ---
        to_load: list[str] = []
        for row in range(lo, hi + 1):
            if row in self._loaded_rows:
                continue
            item = self.model.item(row)
            if item is None or item.data(IS_DIR_ROLE):
                continue
            path_str = item.data(Qt.UserRole)
            if path_str and item.data(PIXMAP_ROLE) is None:
                to_load.append(path_str)

        if not to_load:
            return

        # --- ソフト停止（ブロックしない）して新しいウィンドウ分だけ起動 ---
        self._soft_stop_thumbnail_worker()
        self._start_thumbnail_worker(to_load, self._view_generation)

    # ------------------------------------------------------------------ #
    # ナビゲーション
    # ------------------------------------------------------------------ #

    def _clear_breadcrumb(self):
        while self.breadcrumb_layout.count():
            item = self.breadcrumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _make_crumb(self, text: str, folder: str | None, is_last: bool) -> QPushButton:
        """パンくずの1セグメント。folder=None はホーム、folder=str はそのフォルダへ移動。"""
        btn = QPushButton(text)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setFlat(True)
        weight = "bold" if is_last else "normal"
        color = "#3a2000" if is_last else "#6a5030"
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                padding: 2px 6px; color: {color};
                font-size: 11pt; font-weight: {weight};
            }}
            QPushButton:hover {{ color: #1a7a2c; text-decoration: underline; }}
        """)
        if is_last:
            btn.setEnabled(False)
            btn.setStyleSheet(btn.styleSheet() + "QPushButton:disabled { color: #3a2000; }")
        else:
            btn.clicked.connect(lambda: self._navigate_to(folder))
        return btn

    def _navigate_to(self, folder: str | None):
        """パンくずクリック: 指定フォルダ（None=ホーム）へ移動する。"""
        self._series_view = None
        self.current_folder = folder
        self._show_shelf()
        self.refresh_view()

    def _update_breadcrumb(self, series_title: str | None = None):
        """現在の階層をパンくずリストとして再構築する。
        series_title 省略時はシリーズ表示中なら自動でその名前を使う
        （設定変更時など呼び出し側が知らない場合にも正しく再構築できる）。"""
        if series_title is None and self._series_view:
            series_title = self._series_view[0]
        self._clear_breadcrumb()
        # 「現在の階層を表示」OFF: パンくずバー自体を隠す（領域も消す）
        if not self.settings.get("show_hierarchy", True):
            self.breadcrumb_bar.setVisible(False)
            return
        self.breadcrumb_bar.setVisible(True)

        def add_sep():
            sep = QLabel("›")
            sep.setStyleSheet("color: #a08050; font-size: 11pt; padding: 0 1px;")
            self.breadcrumb_layout.addWidget(sep)

        # 末尾に付ける選択アイテム名（シリーズ表示中は付けない）
        sel = self._selected_crumb if series_title is None else None
        has_tail = (series_title is not None) or (sel is not None)

        # ホーム（ルート本棚）
        is_home_last = (self.current_folder is None and not has_tail)
        self.breadcrumb_layout.addWidget(
            self._make_crumb("🏠 " + tr("crumb_home"), None, is_home_last))

        segments: list[tuple[str, str]] = []  # (表示名, フォルダパス)
        if self.current_folder is not None:
            cur = Path(self.current_folder)
            # current_folder を含む登録ルートを探す
            root = None
            for p in self.registered_items:
                rp = Path(p)
                if rp.suffix:
                    continue
                if cur == rp or rp in cur.parents:
                    if root is None or len(str(rp)) > len(str(root)):
                        root = rp
            if root is not None:
                base = root.parent
                rel = cur.relative_to(base)
                acc = base
                for part in rel.parts:
                    acc = acc / part
                    segments.append((part, str(acc)))
            else:
                segments.append((cur.name or str(cur), str(cur)))

        for i, (name, path) in enumerate(segments):
            add_sep()
            last = (i == len(segments) - 1) and not has_tail
            self.breadcrumb_layout.addWidget(self._make_crumb(name, path, last))

        # シリーズ内表示中はシリーズ名を末尾に付ける
        if series_title is not None:
            add_sep()
            self.breadcrumb_layout.addWidget(self._make_crumb(series_title, None, True))

        # 選択中のファイル/フォルダ名を末尾に付ける
        if sel is not None:
            add_sep()
            self.breadcrumb_layout.addWidget(self._make_crumb(sel, None, True))

        # 内容に合わせてサイズを確定し、本棚の左下へ配置する
        self.breadcrumb_bar.show()
        self.breadcrumb_bar.adjustSize()
        self._reposition_breadcrumb()
        # 設定トグルON直後など、表示状態が確定する前に呼ばれた場合に備えて
        # イベントループ処理後にもう一度配置・前面化する（即時反映のため）。
        QTimer.singleShot(0, self._reposition_breadcrumb)

    def _reposition_breadcrumb(self):
        """パンくずバーを本棚(list_view)の左下に配置する（最下段に軽くかぶる位置）。"""
        bar = self.breadcrumb_bar
        if not bar.isVisible():
            return
        bar.adjustSize()
        lv = self.list_view
        x = 10
        y = lv.height() - bar.height() - 8
        bar.move(x, max(0, y))
        bar.raise_()

    def go_home(self):
        self._series_view = None
        self.current_folder = None
        self._show_shelf()
        self.refresh_view()

    def go_parent(self):
        # シリーズ内表示中 → 元のフォルダ表示へ戻る
        if self._series_view:
            self._series_view = None
            self.refresh_view()
            return
        if self.current_folder is None:
            return
        parent = Path(self.current_folder).parent
        # Pathオブジェクトで比較してOS問わず正しく動作させる
        registered_dirs = [Path(p) for p in self.registered_items if not Path(p).suffix]
        under_registered = any(
            parent == r or r in parent.parents
            for r in registered_dirs
        )
        self.current_folder = str(parent) if under_registered else None
        self._show_shelf()
        self.refresh_view()

    def _on_current_changed(self, current, previous=None):
        """カレント項目が変わったら（マウスクリック・キーボード移動の両方）
        その名前をパンくずリスト末尾に表示する。"""
        if current is None or not current.isValid():
            return
        item = self.model.itemFromIndex(current)
        if not item or item.data(PLACEHOLDER_ROLE) or not item.data(Qt.UserRole):
            return
        name = item.data(TITLE_ROLE) or Path(item.data(Qt.UserRole)).name
        if name == self._selected_crumb:
            return
        self._selected_crumb = name
        self._update_breadcrumb()

    def _update_action_buttons(self):
        """選択状態に応じて「本として開く」「開く」ボタンの表示・有効状態を更新する"""
        indexes = self.list_view.selectedIndexes()
        if not indexes:
            self.btn_open_as_book.setVisible(False)
            self.btn_open.setEnabled(False)
            return
        item = self.model.itemFromIndex(indexes[0])
        if not item:
            self.btn_open_as_book.setVisible(False)
            self.btn_open.setEnabled(False)
            return
        self.btn_open.setEnabled(True)
        is_dir = item.data(IS_DIR_ROLE)
        if is_dir is None:
            path = item.data(Qt.UserRole) or ""
            is_dir = not bool(Path(path).suffix)
        self.btn_open_as_book.setVisible(bool(is_dir))

    def _open_selected_item(self):
        """「開く」ボタン: 選択アイテムをダブルクリックと同じ動作で開く"""
        indexes = self.list_view.selectedIndexes()
        if not indexes:
            return
        self.on_double_click(indexes[0])

    def _open_folder_as_book(self):
        """「本として開く」ボタン: 選択フォルダ内の画像ファイルを本として開く"""
        indexes = self.list_view.selectedIndexes()
        if not indexes:
            return
        item = self.model.itemFromIndex(indexes[0])
        if not item:
            return
        path = Path(item.data(Qt.UserRole))
        is_dir = item.data(IS_DIR_ROLE)
        if is_dir is None:
            is_dir = not bool(path.suffix)
        if not is_dir:
            return
        from utils import natural_sort_key
        _IMG_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'}
        try:
            images = sorted(
                [p for p in path.iterdir()
                 if p.suffix.lower() in _IMG_EXTS and not p.name.startswith('.')],
                key=lambda p: natural_sort_key(p.name)
            )
        except Exception:
            return
        if images:
            self._open_viewer(images[0])

    def on_double_click(self, index):
        item = self.model.itemFromIndex(index)
        if not item or item.data(PLACEHOLDER_ROLE) or not item.data(Qt.UserRole):
            return
        path = Path(item.data(Qt.UserRole))
        # シリーズ代表アイテム → シリーズ内の一覧を表示
        members = item.data(SERIES_ROLE)
        if members:
            self._open_series(item.data(TITLE_ROLE) or path.stem, members)
            return
        # ワーカーが保存したis_dir情報を使う（is_dir()をメインスレッドで呼ばない）
        is_dir = item.data(IS_DIR_ROLE)
        if is_dir is None:
            is_dir = not bool(path.suffix)
        if is_dir:
            self.current_folder = str(path)
            self.refresh_view()
        else:
            self._open_viewer(path)

    # ------------------------------------------------------------------ #
    # ビューア起動
    # ------------------------------------------------------------------ #

    def _open_viewer(self, path: Path):
        self._save_last_book(path)
        self._add_history(path)
        # RARの場合: libarchiveで読めるなら警告なしで開く
        # libarchiveで読めない場合のみ、unar/unrarがなければ警告を出す
        if path.suffix.lower() in ('.rar', '.cbr', '.7z', '.cb7'):
            from archive import _read_rar_libarchive_cover
            can_read = bool(_read_rar_libarchive_cover(path))
            if not can_read and not _has_rar_support():
                _show_unrar_notice(self)
                return
        # 本棚に戻ったときにこのときの左上アイテムにスクロールするため保存
        self._saved_scroll_path = self._get_current_scroll_path() or str(path)
        self._viewer_file_path = str(path)  # 本棚に戻ったときに選択状態にするため保存
        self._stop_thumbnail_worker()
        self._stop_scan_worker()
        if self.settings["viewer_mode"] == "inline":
            self._open_viewer_inline(path)
        else:
            self._open_viewer_window(path)

    def _open_viewer_window(self, path: Path):
        viewer = ViewerWindow(path, parent=None)
        viewer.setAttribute(Qt.WA_DeleteOnClose)
        viewer.destroyed.connect(lambda: self._viewer_windows.remove(viewer)
                                 if viewer in self._viewer_windows else None)
        self._viewer_windows.append(viewer)
        viewer.show()

    def _open_viewer_inline(self, path: Path):
        if self._inline_viewer is not None:
            self._inline_viewer.close()
            self._inline_viewer = None

        viewer = ViewerWindow(path, parent=self)
        viewer.setWindowFlags(Qt.Widget)
        viewer.back_to_shelf_requested.connect(self._back_to_shelf)
        viewer.open_sibling_requested.connect(self._open_sibling_book)
        self._inline_viewer = viewer

        old = self._stack.widget(1)
        self._stack.removeWidget(old)
        self._stack.insertWidget(1, viewer)
        self._stack.setCurrentIndex(1)
        self.act_back_to_shelf.setVisible(True)
        self.act_up.setVisible(False)
        self.toolbar.setVisible(False)
        self.menuBar().setVisible(False)
        viewer.show()
        viewer.setFocus()
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, viewer.setFocus)
        _QTimer.singleShot(100, viewer.setFocus)
        # 非表示状態で起動した場合はここで表示する
        if not self.isVisible():
            self._show_with_state()
            _QTimer.singleShot(0, viewer.setFocus)
            _QTimer.singleShot(100, viewer.setFocus)

    def _open_sibling_book(self, direction: int):
        """ビューアで開いている本の次(+1)/前(-1)の本を開く"""
        if self._inline_viewer is None:
            return
        current = self._inline_viewer.file_path
        folder = current.parent
        try:
            from utils import natural_sort_key
            # アーカイブファイルのみ対象（フォルダや画像単体は除く）
            book_exts = {".zip", ".rar", ".cbz", ".cbr", ".7z", ".cb7", ".pdf"}
            books = sorted(
                [p for p in folder.iterdir()
                 if p.is_file() and p.suffix.lower() in book_exts],
                key=lambda p: natural_sort_key(p.name)
            )
        except Exception as e:
            print(f"フォルダ一覧取得エラー: {e}")
            return

        if current not in books:
            return
        idx = books.index(current) + direction
        if not (0 <= idx < len(books)):
            # 端に達した場合は何もしない
            return

        # 進捗を保存してから次の本を開く
        if self._inline_viewer.pages:
            from viewer import save_progress
            save_progress(current, self._inline_viewer.current_index)
        self._viewer_file_path = str(books[idx])
        self._open_viewer(books[idx])

    def _back_to_shelf(self):
        # フルスクリーンのまま本棚に戻るとタイトルバーが出ず操作不能になるため解除
        if self.isFullScreen():
            if getattr(self, "_was_maximized_before_fullscreen", False):
                self.showMaximized()
            else:
                self.showNormal()
        self._show_shelf()
        # ビューアの進捗を保存（closeEventは呼ばれないため明示的に保存）
        if self._inline_viewer is not None and self._inline_viewer.pages:
            from viewer import save_progress
            save_progress(self._inline_viewer.file_path, self._inline_viewer.current_index)
        # ビューアで開いていたファイルのキャッシュ状態を更新
        self._update_cached_role(self._viewer_file_path)
        if self._saved_scroll_path and self._item_map:
            # 本棚が既に構築済み → そのままスクロール復元
            self._restore_scroll_position()
        else:
            # 本棚が未構築 → list_viewとloading_labelを非表示にしてスキャン
            # スキャン完了後にスクロール復元してから表示する
            self._pending_back_scroll = self._saved_scroll_path
            self._saved_scroll_path = None
            self.list_view.setVisible(False)
            self.loading_label.setVisible(False)
            self.refresh_view()

    def _update_cached_role(self, path_str: str | None):
        """指定パスのアイテムのCACHED_ROLEとPROGRESS_ROLEを更新して再描画"""
        if not path_str:
            return
        item = self._item_map.get(path_str)
        if not item:
            return
        p = Path(path_str)
        if p.suffix.lower() not in ('.zip', '.cbz', '.rar', '.cbr', '.7z', '.cb7', '.pdf'):
            return
        from page_cache import get_cached_pages, get_cached_names
        from viewer import get_saved_page
        # キャッシュ済みフラグ
        is_cached = get_cached_pages(p) is not None
        item.setData(is_cached, CACHED_ROLE)
        # しおり状態
        saved = get_saved_page(p)
        names = get_cached_names(p)
        total = len(names) if names else 0
        if saved > 0:
            names = get_cached_names(p)
            total = len(names) if names else 0
            if total > 0 and saved >= total - 1:
                item.setData('done', PROGRESS_ROLE)
            else:
                item.setData('reading', PROGRESS_ROLE)
        # 再描画
        index = self.model.indexFromItem(item)
        if index.isValid():
            self.list_view.update(index)

    def _back_to_shelf_show(self):
        """スキャン完了後にスクロール復元してリストビューを表示する"""
        if self._pending_back_scroll:
            self._saved_scroll_path = self._pending_back_scroll
            self._pending_back_scroll = None
        self.list_view.setVisible(True)
        if self._saved_scroll_path:
            QTimer.singleShot(50, self._restore_scroll_position)

    def _restore_scroll_position(self):
        """指定パスのアイテムを画面上部にスクロールし、ビューアで開いたファイルを選択状態にする"""
        if not self._saved_scroll_path:
            if not self.isVisible():
                self._show_with_state()
            return
        path_str = self._saved_scroll_path
        self._saved_scroll_path = None
        # スクロール
        item = self._item_map.get(path_str)
        if item:
            index = self.model.indexFromItem(item)
            if index.isValid():
                self.list_view.scrollTo(index, QListView.PositionAtTop)
        # ビューアで開いていたファイルを選択状態にする
        if self._viewer_file_path:
            sel_item = self._item_map.get(self._viewer_file_path)
            if sel_item:
                sel_index = self.model.indexFromItem(sel_item)
                if sel_index.isValid():
                    self.list_view.setCurrentIndex(sel_index)
            self._viewer_file_path = None
        if not self.isVisible():
            self._show_with_state()

    def _show_shelf(self):
        self._stack.setCurrentIndex(0)
        self.act_back_to_shelf.setVisible(False)
        self.act_up.setVisible(True)
        self.toolbar.setVisible(True)
        self.menuBar().setVisible(True)

    # ------------------------------------------------------------------ #
    # 右クリックメニュー
    # ------------------------------------------------------------------ #

    def show_context_menu(self, position):
        menu = QMenu()
        menu.addAction(tr("ctx_remove")).triggered.connect(self.remove_selected)
        menu.exec(self.list_view.mapToGlobal(position))

    def remove_selected(self):
        indexes = self.list_view.selectedIndexes()
        if not indexes:
            return
        item = self.model.itemFromIndex(indexes[0])
        path_str = item.data(Qt.UserRole)
        if path_str in self.registered_items:
            self.registered_items.remove(path_str)
            self.save_library()
            self.refresh_view()

    # ------------------------------------------------------------------ #
    # 終了処理（全スレッドを安全に停止）
    # ------------------------------------------------------------------ #

    def _restore_window_state(self):
        """保存されたウィンドウサイズ・位置を復元する（最大化はshow()後に適用）"""
        try:
            data = self._read_last_loc_data()
            # サイズ・位置は先に設定（最大化フラグはshow()後に適用するので保持）
            self._pending_maximized   = data.get("window_maximized", False)
            self._pending_fullscreen  = data.get("window_fullscreen", False)
            if not self._pending_maximized and not self._pending_fullscreen:
                if "window_w" in data:
                    self.setGeometry(
                        data.get("window_x", 100),
                        data.get("window_y", 100),
                        data.get("window_w", 1440),
                        data.get("window_h", 920),
                    )
        except Exception:
            self._pending_maximized  = False
            self._pending_fullscreen = False

    def closeEvent(self, event):
        # インラインビューアのスレッドを先に停止（child widget は closeEvent が呼ばれないため）
        if self._inline_viewer is not None:
            try:
                self._inline_viewer._stop_strip_worker()
            except Exception:
                pass
            try:
                from viewer import save_progress
                if self._inline_viewer.pages:
                    save_progress(self._inline_viewer.file_path,
                                  self._inline_viewer.current_index)
            except Exception:
                pass

        # 全ワーカーにstopフラグを立てる
        if self._thumb_worker:
            self._thumb_worker.stop()
        if self._search_worker:
            self._search_worker.stop()

        # シグナルを切断してからスレッドを強制停止
        for worker, thread in [
            (self._thumb_worker,   self._thumb_thread),
            (self._scan_worker,    self._scan_thread),
            (self._search_worker,  self._search_thread),
            (self._startup_worker, self._startup_thread),
        ]:
            if worker:
                for sig_name in ('thumbnails_batch', 'scan_done', 'result_ready', 'done'):
                    try:
                        getattr(worker, sig_name, None) and getattr(worker, sig_name).disconnect()
                    except RuntimeError:
                        pass
            if thread:
                try:
                    if thread.isRunning():
                        thread.quit()
                        if not thread.wait(2000):   # 2秒待って終わらなければ強制終了
                            thread.terminate()
                            thread.wait(2000)
                except RuntimeError:
                    pass

        if self.settings["remember_last_location"]:
            self._save_last_location()

        # 全状態を1回にまとめて保存
        self._save_all_state()
        super().closeEvent(event)

    def _save_all_state(self):
        """終了時の全状態をまとめて1回で保存する"""
        try:
            data = self._read_last_loc_data()

            # ① ビューア/本棚モード
            is_viewer = (self._stack.currentIndex() == 1
                         and self._inline_viewer is not None)
            data["exit_in_viewer"] = is_viewer

            # ② 本棚スクロール位置（本棚モードのときのみ更新）
            if not is_viewer:
                scroll_path = self._get_current_scroll_path()
                if scroll_path:
                    data["shelf_scroll_path"] = scroll_path

            # ③ ウィンドウ状態
            state = self.windowState()
            data["window_maximized"] = bool(state & Qt.WindowMaximized)
            data["window_fullscreen"] = bool(state & Qt.WindowFullScreen)
            if not data["window_maximized"] and not data["window_fullscreen"]:
                geo = self.geometry()
                data["window_x"] = geo.x()
                data["window_y"] = geo.y()
                data["window_w"] = geo.width()
                data["window_h"] = geo.height()

            LAST_LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAST_LOC_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f"状態保存エラー: {e}")

    def _get_current_scroll_path(self) -> str | None:
        """現在表示中の左上のアイテムパスを返す（PositionAtTopで復元するため）"""
        try:
            vp = self.list_view.viewport()
            w, h = vp.width(), vp.height()
            if w <= 0 or h <= 0:
                return None
            # 左上隅のアイテムを取得
            for cx, cy in [(10, 10), (w // 2, 10), (10, 30)]:
                index = self.list_view.indexAt(QPoint(cx, cy))
                if index.isValid():
                    item = self.model.itemFromIndex(index)
                    if item:
                        path = item.data(Qt.UserRole)
                        if path:
                            return path
        except Exception as e:
            return None


# ============================================================
# スレッド安全停止ヘルパー
# ============================================================

def _make_gear_icon(size: int = 32) -> QIcon:
    """QPainterで歯車アイコンを描画（QIcon.fromTheme未対応環境用）"""
    import math
    from PySide6.QtGui import QPainter, QBrush, QPainterPath
    from PySide6.QtCore import QPointF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)

    cx, cy = size / 2.0, size / 2.0
    n = 8          # 歯数
    r1 = size * 0.46  # 歯先半径
    r2 = size * 0.30  # 歯底半径
    r0 = size * 0.11  # 中心穴半径
    tooth = 0.40   # 歯幅（1ピッチに対する割合）
    step = 2 * math.pi / n

    path = QPainterPath()
    first = True
    for i in range(n):
        base = step * i
        for r, a in [
            (r2, base - step * (0.5 - tooth * 0.5)),
            (r1, base - step * tooth * 0.5),
            (r1, base + step * tooth * 0.5),
            (r2, base + step * (0.5 - tooth * 0.5)),
        ]:
            x = cx + r * math.cos(a)
            y = cy + r * math.sin(a)
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)
    path.closeSubpath()
    path.addEllipse(QPointF(cx, cy), r0, r0)  # OddEvenFillで中心穴を抜く

    color = QApplication.palette().windowText().color()
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.NoPen)
    painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def stop_thread_safely(thread: QThread | None, timeout_ms: int = 3000):
    if thread is None:
        return
    if not thread.isRunning():
        return
    thread.quit()
    if not thread.wait(timeout_ms):
        # terminate() は "QThread: Destroyed while still running" を引き起こすため使わない。
        # タイムアウトしても処理継続 — ネットワーク遅延による一時的なブロックは自然解消する。
        print(f"警告: スレッドが {timeout_ms}ms 以内に終了しなかった（継続して待機中）。")


if __name__ == "__main__":
    # ネットワークドライブが未接続のとき Windows が出す「場所が利用できません」
    # ダイアログを抑制する。Path.exists() 等がエラーコードを返すだけになる。
    if sys.platform == "win32":
        import ctypes as _ctypes
        _ctypes.windll.kernel32.SetErrorMode(0x8001)  # SEM_FAILCRITICALERRORS | SEM_NOOPENFILEERRORBOX
        # タスクバーグループIDを明示設定。未設定だと python.exe や旧EXEと同じIDに
        # なり、古いキャッシュアイコンがタスクバーに表示され続ける。
        try:
            _ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                'ComicViewer.App'
            )
        except Exception:
            pass

    # venv PySide6 の fcitx プラグインは fcitx5 用のため、
    # fcitx4 環境では接続できず IME が動かない。
    # ibus が動いていれば QT_IM_MODULE=ibus に切り替えて直接入力を有効にする。
    import os, shutil, subprocess
    _qt_im = os.environ.get("QT_IM_MODULE", "")
    if _qt_im == "fcitx" and not shutil.which("fcitx5"):
        try:
            r = subprocess.run(["pgrep", "-x", "ibus-daemon"], capture_output=True)
            if r.returncode == 0:
                os.environ["QT_IM_MODULE"] = "ibus"
        except Exception:
            pass

    # HighDPI環境（スケーリング設定）に応じてUIサイズを自動調整する
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # アプリアイコン設定（タスクバー・タイトルバー・Alt+Tab）
    # 開発時は __file__ の隣の icon.png、EXE 時は sys._MEIPASS に展開された icon.png を使う
    _icon_base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
    _icon_file = _icon_base / 'icon.png'
    if _icon_file.exists():
        app.setWindowIcon(QIcon(str(_icon_file)))

    window = BookshelfWindow()
    # show()はスクロール復元後に_show_after_restoreから呼ばれる
    # ただし念のため最初は非表示にしておく
    window.hide()
    sys.exit(app.exec())
