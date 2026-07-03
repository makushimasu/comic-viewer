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
_UNRAR_NOTICE_FILE = APP_DIR / "unrar_notice_shown.flag"

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

    def __init__(self, parent=None):
        super().__init__(parent)
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
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        # QAbstractItemViewは既定でモデルベースD&Dを判定するため、
        # URLドロップは自前でacceptし続ける必要がある
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
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
        # その上に棚板と影を重ねる
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._draw_shelf_boards(painter)
        painter.end()

    def _update_grid_size(self):
        """ビューポート幅いっぱいにアイテムが均等配置されるようgridSizeを動的調整する"""
        vp_w = self.viewport().width()
        if vp_w <= 0:
            return
        natural_w = self.sizeHintForColumn(0)
        if natural_w <= 0:
            natural_w = self.iconSize().width() + 4   # H_MARGIN * 2 フォールバック
        natural_h = self.sizeHintForRow(0)
        if natural_h <= 0:
            return
        cols = max(1, vp_w // natural_w)
        cell_w = vp_w // cols
        self.setGridSize(QSize(cell_w, natural_h))

    def rowsInserted(self, parent, start, end):
        super().rowsInserted(parent, start, end)
        if start == 0:   # 最初のアイテム追加時にグリッドサイズを設定
            self._update_grid_size()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_grid_size()
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
        """各段の下端に棚板と影を描画する"""
        model = self.model()
        if not model or model.rowCount() == 0:
            return

        item_h = self.sizeHintForRow(0)
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

    # 後方互換のため旧シグナルも残す（_on_thumbnail_readyが参照しているため）
    thumbnail_ready  = Signal(str, QPixmap, int)

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
        self._pixmap_lru: OrderedDict = OrderedDict()   # path_str → QStandardItem
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

        self.path_label = QLabel()
        self.path_label.setFont(QFont("sans-serif", 11, QFont.Weight.Bold))
        self.path_label.setStyleSheet(
            "padding: 12px; background: #f0e6d2; color: #1a1a1a; border-radius: 6px;"
        )
        self.path_label.setSizePolicy(SP.Expanding, SP.Preferred)
        header_row.addWidget(self.path_label)

        self.scan_progress_label = QLabel("")
        self.scan_progress_label.setFont(QFont("sans-serif", 10))
        self.scan_progress_label.setStyleSheet("color: #7a5020; padding: 0 10px;")
        self.scan_progress_label.setVisible(False)
        header_row.addWidget(self.scan_progress_label)

        self.add_btn = QPushButton("＋")
        self.add_btn.setFixedSize(40, 40)
        self.add_btn.setFont(QFont("sans-serif", 16, QFont.Weight.Bold))
        self.add_btn.setToolTip(tr("add_btn_tip"))
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #5a8a3c; color: white;
                border-radius: 20px; font-size: 20px;
            }
            QPushButton:hover   { background: #4a7a2c; }
            QPushButton:pressed { background: #3a6a1c; }
        """)
        self.add_btn.clicked.connect(self._show_add_menu)
        header_row.addWidget(self.add_btn)
        layout.addLayout(header_row)

        self.filepath_label = QLabel("")
        self.filepath_label.setFont(QFont("monospace", 9))
        self.filepath_label.setStyleSheet("color: #555; padding: 2px 12px;")
        self.filepath_label.setVisible(self.settings["show_filepath"])
        layout.addWidget(self.filepath_label)

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
        self.list_view.clicked.connect(self._on_item_clicked)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self.show_context_menu)
        self.list_view.dragEnterEvent = self.dragEnterEvent
        self.list_view.dropEvent = self.dropEvent

        layout.addWidget(self.list_view)

        self.model = QStandardItemModel()
        self.list_view.setModel(self.model)

        # 選択状態変更時にアクションボタンを更新
        self.list_view.selectionModel().selectionChanged.connect(
            lambda *_: self._update_action_buttons()
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

        self.act_back_to_shelf = toolbar.addAction(toolbar_icon("back", "go-previous"), tr("toolbar_back"))
        self.act_back_to_shelf.triggered.connect(self._back_to_shelf)
        self.act_back_to_shelf.setVisible(False)

        spacer = QWidget()
        spacer.setSizePolicy(SP.Expanding, SP.Preferred)
        toolbar.addWidget(spacer)

        _icon_settings = toolbar_icon("settings", "preferences-system")
        if _icon_settings.isNull():
            _icon_settings = _make_gear_icon(int(toolbar.iconSize().width()))
        settings_btn = toolbar.addAction(_icon_settings, tr("toolbar_settings"))
        settings_btn.triggered.connect(self.open_settings)
        settings_btn.setToolTip(tr("toolbar_settings_tip"))

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
        menu.exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

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
        self.filepath_label.setStyleSheet("color: #5a3800; padding: 2px 12px; background: transparent;")
        self.count_label.setStyleSheet("color: #7a5020; padding: 2px 8px; background: transparent;")
        self.loading_label.setStyleSheet("color: rgba(80,50,10,180); padding: 20px; background: transparent;")

    def _apply_settings(self, rebuild: bool = True):
        sb_policy = Qt.ScrollBarAlwaysOn if self.settings["scrollbar_always"] else Qt.ScrollBarAsNeeded
        self.list_view.setVerticalScrollBarPolicy(sb_policy)
        self.filepath_label.setVisible(self.settings["show_filepath"])
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

    def _load_last_location(self) -> str | None:
        data = self._read_last_loc_data()
        folder = data.get("folder")
        if folder and Path(folder).exists():
            return folder
        return None

    def _save_last_book(self, file_path: Path):
        LAST_LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = self._read_last_loc_data()
        data["last_book"] = str(file_path)
        # ビューアを開いた時点のフォルダを保存（本棚に戻る際に使用）
        data["last_book_folder"] = self.current_folder
        LAST_LOC_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def _load_last_book(self) -> Path | None:
        data = self._read_last_loc_data()
        p = data.get("last_book")
        if p and Path(p).exists():
            return Path(p)
        return None

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

    def _check_unrar_once(self):
        """起動時に1回だけunrarがない場合に通知する"""
        if _has_rar_support():
            return
        if _UNRAR_NOTICE_FILE.exists():
            return  # 既に通知済み
        _UNRAR_NOTICE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _UNRAR_NOTICE_FILE.touch()
        _show_unrar_notice(self)

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
        self.add_btn.setVisible(is_root)

        label = (tr("shelf_top", n=len(self.registered_items)) if is_root
                 else tr("shelf_folder", folder=self.current_folder))
        self.path_label.setText(label if self.settings["show_hierarchy"] else "")

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

    def _on_thumbnail_ready(self, path_str: str, pixmap: QPixmap, generation: int):
        if generation != self._view_generation:
            return
        item = self._item_map.get(path_str)
        if item:
            self._register_pixmap(path_str, item, pixmap)

    _PIXMAP_MAX = 400   # RAMに保持するPixmap最大件数（400件 × ~200KB ≈ 80MB）

    def _register_pixmap(self, path_str: str, item, pixmap: QPixmap):
        """Pixmapをモデルに登録して _loaded_rows を更新する。"""
        item.setData(pixmap, PIXMAP_ROLE)
        idx = self.model.indexFromItem(item)
        if idx.isValid():
            self._loaded_rows.add(idx.row())
        self._pixmap_lru[path_str] = item   # 後方互換のため保持

    def _evict_distant_pixmaps(self):
        """現在のスクロール位置から遠いアイテムのPixmapを優先的に解放する。
        これにより、画面上の可視アイテムが消えるのを防ぐ。"""
        excess = len(self._pixmap_lru) - self._PIXMAP_MAX
        if excess <= 0:
            return

        item_h = self.list_view.sizeHintForRow(0)
        item_w = self.list_view.sizeHintForColumn(0)
        vp_w   = self.list_view.viewport().width()
        vp_h   = self.list_view.viewport().height()
        scroll_y = self.list_view.verticalScrollBar().value()

        if item_h <= 0 or item_w <= 0 or vp_w <= 0:
            # サイズ不明時は単純に古い順に解放（フォールバック）
            for _ in range(excess):
                if self._pixmap_lru:
                    _, old_item = self._pixmap_lru.popitem(last=False)
                    old_item.setData(None, PIXMAP_ROLE)
            return

        cols = max(1, vp_w // item_w)
        # 画面中央の「ビジュアル行」番号
        visible_center_vrow = (scroll_y + vp_h // 2) // item_h

        # 全エントリについてビジュアル行との距離を算出
        scored: list[tuple[int, str, object]] = []
        for path_str, item in self._pixmap_lru.items():
            idx = self.model.indexFromItem(item)
            if not idx.isValid():
                scored.append((999999, path_str, item))
                continue
            visual_row = idx.row() // cols
            dist = abs(visual_row - visible_center_vrow)
            scored.append((dist, path_str, item))

        # 距離が遠い順（降順）にソートして excess 件を解放
        scored.sort(key=lambda x: x[0], reverse=True)
        for i in range(min(excess, len(scored))):
            dist, path_str, old_item = scored[i]
            if path_str in self._pixmap_lru:
                del self._pixmap_lru[path_str]
                old_item.setData(None, PIXMAP_ROLE)

    def _reload_visible_pixmaps(self):
        """スクロール後、画面内にあってPixmapが解放されたアイテムをキャッシュから再読込む"""
        from core import get_cache_path
        vp = self.list_view.viewport()
        vp_rect = vp.rect()
        # ビューポートを格子状にサンプリングして可視インデックスを収集
        seen: set[str] = set()
        missing: list[str] = []
        step = 40
        for y in range(step // 2, vp_rect.height() + step, step):
            for x in range(step // 2, vp_rect.width() + step, step):
                idx = self.list_view.indexAt(QPoint(x, y))
                if not idx.isValid():
                    continue
                path_str = idx.data(Qt.UserRole)
                if not path_str or path_str in seen:
                    continue
                seen.add(path_str)
                item = self._item_map.get(path_str)
                if item and item.data(PIXMAP_ROLE) is None:
                    missing.append(path_str)
        if not missing:
            return

        thumb_size = (
            self.settings.get("thumbnail_width", 190),
            self.settings.get("thumbnail_height", 270),
        )
        gen = self._view_generation

        def _load():
            from PIL import Image
            results = []
            for path_str in missing:
                cache = get_cache_path(Path(path_str))
                if not cache.exists():
                    continue
                try:
                    img = Image.open(cache)
                    img.load()
                    img.thumbnail(thumb_size, Image.LANCZOS)
                    results.append((path_str, pil_to_qpixmap(img)))
                except Exception:
                    pass
            QTimer.singleShot(0, lambda: _apply(results))

        def _apply(results):
            if self._view_generation != gen:
                return
            for path_str, px in results:
                item = self._item_map.get(path_str)
                if item:
                    self._register_pixmap(path_str, item, px)

        import threading
        threading.Thread(target=_load, daemon=True).start()

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

    def _on_scroll_stabilized(self):
        """スクロール停止後: 遠いPixmapを退避 → 画面内の空きを再読込（未使用・互換用）"""
        self._load_window_thumbnails()

    # ------------------------------------------------------------------ #
    # ナビゲーション
    # ------------------------------------------------------------------ #

    def go_home(self):
        self.current_folder = None
        self.filepath_label.setText("")
        self._show_shelf()
        self.refresh_view()

    def go_parent(self):
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
        self.filepath_label.setText("")
        self._show_shelf()
        self.refresh_view()

    def _on_item_clicked(self, index):
        if not self.settings["show_filepath"]:
            return
        item = self.model.itemFromIndex(index)
        if item:
            self.filepath_label.setText(item.data(Qt.UserRole))

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
        if not item:
            return
        path = Path(item.data(Qt.UserRole))
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
        self.filepath_label.setText("")  # 前回選択ファイルのパス表示をクリア
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
    # ドラッグ&ドロップ
    # ------------------------------------------------------------------ #

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        added = 0
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.exists() and str(path) not in self.registered_items:
                self.registered_items.append(str(path))
                added += 1
        if added > 0:
            self.save_library()
            self.refresh_view()
            _info_msg(self, tr("drop_ok_title"), tr("drop_ok_text", n=added))

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

    def _save_shelf_scroll_position(self):
        """本棚の現在のスクロール位置を保存する"""
        try:
            # スクロールバーの値からアイテムインデックスを計算
            # （ウィンドウが非表示でも動作する）
            item_h = self.list_view.sizeHintForRow(0)
            if item_h <= 0 or self.model.rowCount() == 0:
                return

            scroll_y = self.list_view.verticalScrollBar().value()
            vp_w = self.list_view.viewport().width()
            if vp_w <= 0:
                vp_w = self.list_view.width()

            item_w = self.list_view.sizeHintForColumn(0)
            if item_w <= 0:
                item_w = self.settings.get("thumbnail_width", 190) + 4
            cols = max(1, vp_w // max(item_w, 1))

            # 画面中央に表示されている行を計算
            vp_h = self.list_view.viewport().height()
            if vp_h <= 0:
                vp_h = self.list_view.height()
            center_y = scroll_y + vp_h // 2
            row = center_y // max(item_h, 1)
            row = max(0, min(row, self.model.rowCount() // cols))
            item_index = row * cols

            if item_index >= self.model.rowCount():
                item_index = 0

            item = self.model.item(item_index)
            if item:
                path_str = item.data(Qt.UserRole)
                if path_str:
                    data = self._read_last_loc_data()
                    data["shelf_scroll_path"] = path_str
                    LAST_LOC_FILE.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding='utf-8'
                    )
        except Exception as e:
            print(f"スクロール位置保存エラー: {e}")

    def _save_exit_mode(self):
        """終了時にビューアモードだったか本棚モードだったかを記録"""
        try:
            data = self._read_last_loc_data()
            # インラインビューアが開いていればビューアモード終了
            is_viewer = (self._stack.currentIndex() == 1 and self._inline_viewer is not None)
            data["exit_in_viewer"] = is_viewer
            LAST_LOC_FILE.parent.mkdir(parents=True, exist_ok=True)
            LAST_LOC_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
            )
        except Exception as e:
            print(f"終了モード保存エラー: {e}")

    def _save_window_state(self):
        """ウィンドウサイズ・位置・最大化状態を保存する"""
        try:
            data = self._read_last_loc_data()
            state = self.windowState()
            data["window_maximized"] = bool(state & Qt.WindowMaximized)
            data["window_fullscreen"] = bool(state & Qt.WindowFullScreen)
            if not (state & Qt.WindowMaximized) and not (state & Qt.WindowFullScreen):
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
            print(f"ウィンドウ状態保存エラー: {e}")

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
