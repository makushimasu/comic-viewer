# viewer.py
import io
import json
import hashlib
from pathlib import Path

from PIL import Image

from PySide6.QtWidgets import (
    QMainWindow, QLabel, QScrollArea, QSizePolicy,
    QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QFrame
)
from PySide6.QtGui import QPixmap, QImage, QAction, QIcon, QFont, QColor
from PySide6.QtCore import Qt, QSize, QThread, Signal, QObject

from core import safe_open_image, safe_open_image_from_path
from i18n import tr


IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp')

from appdir import APP_DIR

PROGRESS_FILE = APP_DIR / "progress.json"
APP_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 既読進捗
# ============================================================

def _progress_key(file_path: Path) -> str:
    return hashlib.md5(str(file_path).encode()).hexdigest()

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def save_progress(file_path: Path, page_index: int):
    data = load_progress()
    key = _progress_key(file_path)
    if key not in data:
        data[key] = {}
    data[key]["path"] = str(file_path)
    data[key]["page"] = page_index
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def get_saved_page(file_path: Path) -> int:
    data = load_progress()
    key = _progress_key(file_path)
    return data.get(key, {}).get("page", 0)


def load_bookmarks(file_path: Path) -> dict:
    """しおりが付いているページindex -> ラベル の辞書を取得"""
    data = load_progress()
    key = _progress_key(file_path)
    raw = data.get(key, {}).get("bookmarks", {})
    if isinstance(raw, list):
        # 旧形式（indexのリスト）との後方互換
        return {int(i): "" for i in raw}
    return {int(k): v for k, v in raw.items()}


def save_bookmarks(file_path: Path, bookmarks: dict):
    """しおりが付いているページindex -> ラベル の辞書を保存"""
    data = load_progress()
    key = _progress_key(file_path)
    if key not in data:
        data[key] = {"path": str(file_path), "page": 0}
    data[key]["bookmarks"] = {str(k): v for k, v in bookmarks.items()}
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def load_rotations(file_path: Path) -> dict:
    """ページごとの回転角度(0/90/180/270)を取得"""
    data = load_progress()
    key = _progress_key(file_path)
    raw = data.get(key, {}).get("rotations", {})
    return {int(k): v for k, v in raw.items()}


def save_rotations(file_path: Path, rotations: dict):
    """ページごとの回転角度(0/90/180/270)を保存"""
    data = load_progress()
    key = _progress_key(file_path)
    if key not in data:
        data[key] = {"path": str(file_path), "page": 0}
    # 0度（回転なし）のエントリは保存しない
    cleaned = {str(k): v for k, v in rotations.items() if v}
    data[key]["rotations"] = cleaned
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


# ============================================================
# PIL → QPixmap
# ============================================================

def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    raw = img.tobytes("raw", "RGB")
    qimage = QImage(raw, img.width, img.height, img.width * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimage)


# ============================================================
# ④ ページ読み込みワーカー
#    アーカイブ展開 / フォルダ列挙 をバックグラウンドで実行
# ============================================================

class PageLoadWorker(QObject):
    """
    ファイルのページリストをバックグラウンドで構築する。
    アーカイブ: bytes のリスト
    単体画像:   Path のリスト
    """
    load_done  = Signal(list, str, int, list)  # (pages, page_type, initial_index, page_names)
    page_ready = Signal(int, bytes)            # (index, data) ZIPストリーミング用
    cache_done   = Signal()                    # キャッシュ保存完了
    cache_start  = Signal()                    # キャッシュ保存開始

    def __init__(self, file_path: Path):
        super().__init__()
        self._file_path = file_path
        self._cancelled = False  # キャンセルフラグ

    def cancel(self):
        """外部から呼んでキャンセルを要求する"""
        self._cancelled = True

    def run(self):
        suffix = self._file_path.suffix.lower()
        pages = []
        page_type = "unknown"
        initial_index = 0
        names = []

        try:
            if suffix in ('.zip', '.cbz', '.rar', '.cbr', '.7z', '.cb7', '.pdf'):
                pages, page_type, names = self._load_archive()
                if self._cancelled:
                    return
                saved = get_saved_page(self._file_path)
                initial_index = saved if 0 < saved < len(pages) else 0

            elif suffix in IMAGE_EXTS:
                siblings = sorted(
                    p for p in self._file_path.parent.iterdir()
                    if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith('.')
                )
                if self._cancelled:
                    return
                pages = siblings
                page_type = "files"
                try:
                    initial_index = siblings.index(self._file_path)
                except ValueError:
                    initial_index = 0
                saved = get_saved_page(self._file_path)
                if 0 < saved < len(pages):
                    initial_index = saved
                names = [p.name for p in pages]

        except Exception as e:
            print(f"PageLoadWorker エラー {self._file_path}: {e}")

        if not self._cancelled:
            if page_type in ("archive", "archive_cached"):
                try:
                    from page_cache import get_cached_names
                    cached_names = get_cached_names(self._file_path)
                    page_names = cached_names if cached_names else (names or [f"{i+1:04d}" for i in range(len(pages))])
                except Exception:
                    page_names = names or [f"{i+1:04d}" for i in range(len(pages))]
            else:
                page_names = names
            self.load_done.emit(pages, page_type, initial_index, page_names)

    def _load_archive(self):
        from archive import read_all_images_with_names, read_zip_streaming, ArchiveError
        from page_cache import get_cached_paths, get_cached_names, save_cached_pages

        suffix = self._file_path.suffix.lower()

        # キャッシュ確認: bytesではなくPathを返してメモリを節約する
        cached_paths = get_cached_paths(self._file_path)
        if cached_paths:
            names = get_cached_names(self._file_path) or [f"{i+1:04d}" for i in range(len(cached_paths))]
            return cached_paths, "archive_cached", names

        # ZIPはストリーミング展開（1ページ目からすぐ表示）
        if suffix in ('.zip', '.cbz'):
            pages = []
            names = []
            for idx, name, data in read_zip_streaming(self._file_path):
                if self._cancelled:
                    return pages, "archive", names
                pages.append(data)
                names.append(name)
                # 最初のページが読めたらすぐ通知
                self.page_ready.emit(idx, data)

            # ZIP内の物理格納順は番号順とは限らないため、
            # 最終結果はファイル名でソートし直す
            if names:
                order = sorted(range(len(names)), key=lambda i: names[i])
                pages = [pages[i] for i in order]
                names = [names[i] for i in order]

            # キャッシュ保存
            if pages:
                try:
                    from settings import load_settings
                    max_mb = load_settings().get("page_cache_mb", 500)
                    if max_mb > 0:
                        worker_ref = self
                        self.cache_start.emit()
                        def _save():
                            save_cached_pages(
                                worker_ref._file_path, pages, max_mb, names,
                                on_done=lambda: worker_ref.cache_done.emit()
                            )
                        import threading
                        threading.Thread(target=_save, daemon=True).start()
                except Exception as e:
                    print(f"[page_cache] キャッシュ保存スキップ: {e}")
            if pages:
                return pages, "archive", names
            # 画像が1枚もないZIP（PDF内包等）は下の全展開処理にフォールバックする

        # PDFはページ単位でレンダリングしながら順次表示（ZIPストリーミングと同方式）
        if suffix == '.pdf':
            from archive import iter_pdf_pages
            pages = []
            names = []
            try:
                for idx, name, data in iter_pdf_pages(self._file_path):
                    if self._cancelled:
                        return pages, "archive", names
                    pages.append(data)
                    names.append(name)
                    # 最初のページが描けたらすぐ通知
                    self.page_ready.emit(idx, data)
            except ArchiveError as e:
                print(f"PDF展開エラー: {e}")
                return [], "archive", []

            # キャッシュ保存（JPEG化済みなので2回目以降は高速）
            if pages:
                try:
                    from settings import load_settings
                    max_mb = load_settings().get("page_cache_mb", 500)
                    if max_mb > 0:
                        worker_ref = self
                        self.cache_start.emit()
                        def _save():
                            save_cached_pages(
                                worker_ref._file_path, pages, max_mb, names,
                                on_done=lambda: worker_ref.cache_done.emit()
                            )
                        import threading
                        threading.Thread(target=_save, daemon=True).start()
                except Exception as e:
                    print(f"[page_cache] キャッシュ保存スキップ: {e}")
            return pages, "archive", names

        # RAR等は従来通り全展開
        try:
            pages, names = read_all_images_with_names(self._file_path)
        except ArchiveError as e:
            print(f"アーカイブ展開エラー: {e}")
            return [], "archive", []

        if pages:
            try:
                from settings import load_settings
                max_mb = load_settings().get("page_cache_mb", 500)
                if max_mb > 0:
                    worker_ref = self
                    self.cache_start.emit()
                    def _save():
                        save_cached_pages(
                            worker_ref._file_path, pages, max_mb, names,
                            on_done=lambda: worker_ref.cache_done.emit()
                        )
                    import threading
                    threading.Thread(target=_save, daemon=True).start()
            except Exception as e:
                print(f"[page_cache] キャッシュ保存スキップ: {e}")

        return pages, "archive", names


# ============================================================
# サムネイル用 簡易アイコン生成（しおりマーク等）
# ============================================================

_BOOKMARK_SVG_PATH = '<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'
_PIN_SVG_PATH = '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 1 1 0 0 0 0-2H8a1 1 0 0 0 0 2 1 1 0 0 1 1 1z"/>'

def _lucide_pixmap_for_thumb(key: str, color: str, size: int) -> QPixmap:
    """サムネイル上に重ねる小アイコン(QPixmap)を生成する"""
    if key == "bookmark":
        inner = _BOOKMARK_SVG_PATH
    elif key == "pin":
        inner = _PIN_SVG_PATH
    else:
        inner = ""
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="{color}" stroke="{color}" stroke-width="1" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )
    try:
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtGui import QPainter as _QPainter
        from PySide6.QtCore import QByteArray
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = _QPainter(pix)
        renderer.render(p)
        p.end()
        return pix
    except Exception:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        return pix


# ============================================================
# ⑤ サムネイルストリップ用バックグラウンドワーカー
# ============================================================

class ThumbStripWorker(QObject):
    """ページサムネイルの画像をバックグラウンドで1枚ずつ生成してシグナルで通知する"""
    thumb_ready = Signal(int, bytes, int, int)  # (index, rgb_raw, width, height)

    def __init__(self, pages: list, page_type: str, rotations: dict):
        super().__init__()
        self._pages = pages
        self._page_type = page_type
        self._rotations = rotations
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for i, page in enumerate(self._pages):
            if self._cancelled:
                return
            self._emit_thumb(i, page)

    def _emit_thumb(self, index: int, page):
        try:
            if self._page_type == "archive":
                # bytes からの開き方
                img = Image.open(io.BytesIO(page))
            else:
                # ファイルパス: lazy open + thumbnail() でJPEGのdraftモードが効いて高速
                img = Image.open(page)

            # thumbnail() はPILがJPEG subsampling(1/2・1/4・1/8スケール)を自動選択するため
            # フルデコードより大幅に高速
            img.thumbnail((86, 108), Image.LANCZOS)

            mode = img.mode
            if mode in ("RGBA", "P"):
                img = img.convert("RGBA")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif mode != "RGB":
                img = img.convert("RGB")

            if not self._cancelled:
                raw = img.tobytes("raw", "RGB")
                self.thumb_ready.emit(index, raw, img.width, img.height)
        except Exception:
            pass


# ============================================================
# ビューアウィンドウ
# ============================================================

class ViewerWindow(QMainWindow):
    """
    pico viewer 風の画像ビューア

    操作:
      ホイール下 / 右矢印 / D / Space : 次のページ
      ホイール上 / 左矢印 / A         : 前のページ
      + / =                           : 拡大
      - / _                           : 縮小
      F                               : ウィンドウ全体 → 幅フィット → 高さフィット → 原寸
      Esc                             : 閉じる（進捗を自動保存）
    """

    FIT_WINDOW = "ウィンドウ全体"
    FIT_WIDTH  = "幅フィット"
    FIT_HEIGHT = "高さフィット"
    FIT_ORIGIN = "原寸"

    back_to_shelf_requested = Signal()  # 「本棚」ボタン押下時に親へ通知
    open_sibling_requested = Signal(int)  # 次の本(+1)/前の本(-1)を開く要求

    def __init__(self, file_path: Path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.pages: list = []
        self._page_type = "unknown"
        self.current_index = 0
        self.zoom = 1.0
        self.fit_mode = self.FIT_WINDOW
        self._original_pixmap: QPixmap | None = None

        # 設定読み込み（1画面に表示するページ数など）
        from settings import load_settings
        self._viewer_settings = load_settings()
        self.pages_per_screen = int(self._viewer_settings.get("pages_per_screen", 1))
        if self.pages_per_screen not in (1, 2):
            self.pages_per_screen = 1

        self._page_names: list = []
        self._caching: bool = False
        self._streaming_done: bool = False  # ZIPストリーミング完了フラグ
        self._page_thread: QThread | None = None
        self._page_worker: PageLoadWorker | None = None
        self._strip_worker: ThumbStripWorker | None = None
        self._strip_thread: QThread | None = None
        self._thumb_labels: dict[int, QLabel] = {}  # index → サムネイルラベル

        # ページごとの回転角度(0/90/180/270) としおり(ページindex集合)
        self._page_rotations: dict[int, int] = load_rotations(self.file_path)
        self._bookmarked_pages: dict[int, str] = load_bookmarks(self.file_path)

        self._slideshow_timer = None   # QTimer
        self._slideshow_running = False
        self._anim_group = None        # 実行中のアニメーショングループ
        self._anim_labels = []         # アニメーション用オーバーレイラベル

        self._build_ui()
        self._start_page_load()   # ← 非同期でページ読み込み開始

    # ------------------------------------------------------------------ #
    # ⑤ 非同期ページ読み込み
    # ------------------------------------------------------------------ #

    def _start_page_load(self):
        """バックグラウンドでページリストを構築する"""
        self._set_loading(True)

        worker = PageLoadWorker(self.file_path)
        thread = QThread(self)   # parent=self → ViewerWindow が生きている間はスレッドも生きる
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.load_done.connect(self._on_load_done)
        worker.load_done.connect(lambda *_: thread.quit())
        worker.page_ready.connect(self._on_page_ready)
        worker.cache_done.connect(self._on_cache_done)
        worker.cache_start.connect(self._on_cache_start)
        # deleteLater は使わない（parent=self で管理するため）

        self._page_worker = worker
        self._page_thread = thread
        thread.start()

    def _on_page_ready(self, index: int, data: bytes):
        """ZIPストリーミング: 1ページ読めたら即追加・表示"""
        # load_done完了後は不要（重複防止）
        if self._streaming_done:
            return

        # pagesリストにリアルタイム追加
        if index == len(self.pages):
            self.pages.append(data)
        elif index < len(self.pages):
            self.pages[index] = data
        else:
            # 欠番があれば埋める
            while len(self.pages) <= index:
                self.pages.append(b'')
            self.pages[index] = data

        if index == 0:
            # 先頭ページ → ローディング解除して即表示
            self._page_type = "archive"
            self.current_index = 0
            self._set_loading(False)
            self._show_page()
        elif index == self.current_index:
            # 現在表示しようとしているページが届いた → 即表示
            self._show_page()
        # ステータスバーのページ数を更新
        self._update_status()

    def _on_load_done(self, pages: list, page_type: str, initial_index: int, page_names: list):
        """ページリスト構築完了 → 全ページ確定"""
        self._streaming_done = True
        current = self.current_index  # ストリーミング中に移動したページを保持
        self.pages = pages
        self._page_type = page_type
        self._page_names = page_names
        # ストリーミング中にユーザーがページを移動していた場合はそのまま維持
        # initial_indexが0より大きい（保存済みページあり）かつまだ移動していない場合のみ反映
        if initial_index > 0 and current == 0:
            self.current_index = initial_index
        else:
            self.current_index = current
        self._set_loading(False)
        self._show_page()
        self._update_status()

        # サムネイル一覧を構築（遅延・段階的に生成）
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(200, self._build_thumbnail_strip)

    def _on_cache_start(self):
        """キャッシュ保存開始"""
        self._caching = True
        self._update_status()

    def _on_cache_done(self):
        """キャッシュ保存完了"""
        self._caching = False
        self._update_status()

    # ------------------------------------------------------------------ #
    # UI 構築
    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.setWindowTitle(f"Comic Viewer  —  {self.file_path.name}")
        self.resize(1000, 800)
        self.setFocusPolicy(Qt.StrongFocus)

        # ローディングラベル（スタックして重ねる）
        from PySide6.QtWidgets import QStackedWidget
        central = QStackedWidget()
        central.setFocusPolicy(Qt.NoFocus)
        self.setCentralWidget(central)

        # ローディング表示
        loading_widget = QLabel(tr("viewer_loading"))
        loading_widget.setAlignment(Qt.AlignCenter)
        loading_widget.setFont(QFont("sans-serif", 14))
        loading_widget.setStyleSheet("background: #1a1a1a; color: #aaaaaa;")
        self.loading_label = loading_widget
        central.addWidget(loading_widget)         # index 0

        # 画像表示
        self.scroll_area = QScrollArea()
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setStyleSheet("background: #1a1a1a; border: none;")
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image_label.setStyleSheet("background: #1a1a1a;")
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(True)
        central.addWidget(self.scroll_area)       # index 1

        # scroll_area上の右クリックも検知できるようイベントフィルタを設定
        self.scroll_area.viewport().installEventFilter(self)
        self.image_label.installEventFilter(self)

        # ---- オーバーレイパネル（右クリックで表示/非表示） ----
        self._overlay_visible = False

        # 木目テクスチャ（main.pyと共通のキャッシュ）をQPixmapとして読み込む
        wood_path = APP_DIR / "wood_cache.png"
        wood_pixmap = QPixmap(str(wood_path)) if wood_path.exists() else None
        if wood_pixmap is not None and wood_pixmap.isNull():
            wood_pixmap = None

        class WoodOverlayWidget(QWidget):
            """背景全体に木目テクスチャをタイル描画するQWidget"""
            def __init__(self, pixmap, parent=None, border_bottom=False, border_top=False, border_right=False):
                super().__init__(parent)
                self._pixmap = pixmap
                self._border_bottom = border_bottom
                self._border_top = border_top
                self._border_right = border_right

            def paintEvent(self, event):
                from PySide6.QtGui import QPainter, QBrush, QPen
                painter = QPainter(self)
                if self._pixmap is not None:
                    painter.fillRect(self.rect(), QBrush(self._pixmap))
                else:
                    painter.fillRect(self.rect(), QColor(0xe8, 0xc8, 0x96))
                if self._border_bottom:
                    pen = QPen(QColor(120, 80, 30, 120))
                    pen.setWidth(2)
                    painter.setPen(pen)
                    painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
                if self._border_top:
                    pen = QPen(QColor(120, 80, 30, 120))
                    pen.setWidth(2)
                    painter.setPen(pen)
                    painter.drawLine(0, 0, self.width(), 0)
                if self._border_right:
                    pen = QPen(QColor(120, 80, 30, 120))
                    pen.setWidth(2)
                    painter.setPen(pen)
                    painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
                painter.end()
                super().paintEvent(event)

        # lucide風のSVGアイコン（黒線＋丸囲みで統一。本棚ツールバーと同スタイル）
        def _circled(glyph: str) -> str:
            """グリフを丸枠の中に縮小配置する。線幅は縮小率を補正して外周と揃える。"""
            return (
                '<circle cx="12" cy="12" r="10"/>'
                '<g transform="translate(12 12) scale(0.55) translate(-12 -12)" '
                'stroke-width="3.4">' + glyph + '</g>'
            )

        LUCIDE_ICONS = {
            "folder-open": _circled('<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H6a2 2 0 0 0-1.9 1.4L2 17V7z"/><path d="M2 17l2.4-7.2A2 2 0 0 1 6.3 8H20a2 2 0 0 1 1.9 2.6L20 17a2 2 0 0 1-1.9 1.4H4a2 2 0 0 1-2-1.4z"/>'),
            "library":     _circled('<path d="M4 3h3v18H4z"/><path d="M9 3h3v18H9"/><path d="M16.5 3.7l3 17.7-3 .5-3-17.7z"/>'),
            "heart":       _circled('<path d="M12 21s-7.5-4.6-9.6-9C1.1 9 2.5 5.5 6 5c2.1-.3 3.8.9 5 3 1.2-2.1 2.9-3.3 5-3 3.5.5 4.9 4 3.6 7-2.1 4.4-9.6 9-9.6 9z"/>'),
            # 元から円形のアイコンは外周をr=10に合わせるだけでよい
            "history":     '<circle cx="12" cy="12" r="10"/><path d="M12 7v5l3 2"/>',
            "fullscreen":  _circled('<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>'),
            "help":        '<circle cx="12" cy="12" r="10"/><path d="M9.1 9a3 3 0 1 1 5.2 2c-.6.6-1.3 1-1.3 2"/><path d="M12 17h.01"/>',
            "settings":    _circled('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.6 1z"/>'),
            # ---- 下部メニュー用 ----
            "book-plus":   _circled('<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5z"/><path d="M9 7h6"/><path d="M12 4v6"/>'),
            "move":        _circled('<polyline points="5 9 2 12 5 15"/><polyline points="9 5 12 2 15 5"/><polyline points="15 19 12 22 9 19"/><polyline points="19 9 22 12 19 15"/><line x1="2" y1="12" x2="22" y2="12"/><line x1="12" y1="2" x2="12" y2="22"/>'),
            "page":        _circled('<rect x="4" y="2" width="16" height="20" rx="2"/><line x1="8" y1="7" x2="16" y2="7"/><line x1="8" y1="11" x2="16" y2="11"/><line x1="8" y1="15" x2="12" y2="15"/>'),
            "bookmark":    _circled('<path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>'),
            "play":        _circled('<polygon points="6 3 20 12 6 21 6 3"/>'),
            "maximize":    _circled('<rect x="3" y="3" width="18" height="18" rx="2"/>'),
            "book-open":   _circled('<path d="M2 4h7a2 2 0 0 1 2 2v14a2 2 0 0 0-2-2H2z"/><path d="M22 4h-7a2 2 0 0 0-2 2v14a2 2 0 0 1 2-2h7z"/>'),
            "flip-horizontal": _circled('<path d="M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3"/><path d="M16 3h3a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-3"/><line x1="12" y1="2" x2="12" y2="22" stroke-dasharray="3 3"/>'),
            "more":        '<circle cx="12" cy="12" r="10"/><path d="M16.5 12h.01"/><path d="M12 12h.01"/><path d="M7.5 12h.01"/>',
        }

        def _lucide_icon(key: str, color: str = "#1a1a1a") -> QIcon:
            inner = LUCIDE_ICONS.get(key, "")
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
                f'fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
            )
            try:
                from PySide6.QtSvg import QSvgRenderer
                from PySide6.QtGui import QPainter as _QPainter
                from PySide6.QtCore import QByteArray
                renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
                pix = QPixmap(28, 28)
                pix.fill(Qt.transparent)
                p = _QPainter(pix)
                renderer.render(p)
                p.end()
                return QIcon(pix)
            except Exception:
                return QIcon()

        # 上部オーバーレイ（木目調・操作ボタン）
        self.top_overlay = WoodOverlayWidget(wood_pixmap, central, border_bottom=True)
        self.top_overlay.setStyleSheet("border: none;")
        top_layout = QHBoxLayout(self.top_overlay)
        top_layout.setContentsMargins(8, 4, 8, 4)
        top_layout.setSpacing(4)

        TOP_BTN_STYLE = """
            QToolButton {
                background: transparent;
                color: #3a2000;
                border: none;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 9pt;
            }
            QToolButton:hover { background: rgba(180, 130, 60, 100); }
            QToolButton:pressed { background: rgba(140, 95, 30, 150); }
        """

        def _mk_top_btn(icon_key, text, slot):
            from PySide6.QtWidgets import QToolButton
            btn = QToolButton()
            btn.setText(text)
            btn.setIcon(_lucide_icon(icon_key))
            btn.setIconSize(QSize(24, 24))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setAutoRaise(True)
            btn.setStyleSheet(TOP_BTN_STYLE)
            btn.clicked.connect(slot)
            return btn

        top_layout.addWidget(_mk_top_btn("folder-open", tr("top_btn_folder"), self.open_containing_folder))
        top_layout.addWidget(_mk_top_btn("library", tr("top_btn_shelf"), self.back_to_shelf_requested_slot))
        top_layout.addWidget(_mk_top_btn("fullscreen", tr("top_btn_fullscreen"), self.toggle_fullscreen))

        top_layout.addStretch()

        # ファイル名・キャッシュ状態ラベル
        self.toolbar_label = QLabel("")
        self.toolbar_label.setFont(QFont("sans-serif", 10))
        self.toolbar_label.setStyleSheet("color: #3a2000; background: transparent;")
        top_layout.addWidget(self.toolbar_label)

        top_layout.addStretch()

        top_layout.addWidget(_mk_top_btn("settings", tr("top_btn_settings"), self.show_viewer_settings))

        self.top_overlay.setVisible(False)

        OVERLAY_STYLE = """
            background: rgba(30, 30, 30, 220);
            color: #e0e0e0;
        """

        # 下部オーバーレイ（操作ボタン・ステータス）
        self.bottom_overlay = WoodOverlayWidget(wood_pixmap, central, border_top=True)
        self.bottom_overlay.setStyleSheet("border: none;")
        bottom_outer = QVBoxLayout(self.bottom_overlay)
        bottom_outer.setContentsMargins(0, 4, 0, 0)
        bottom_outer.setSpacing(2)

        # ---- 上段: アイコンボタン行 ----
        btn_row = WoodOverlayWidget(wood_pixmap, border_bottom=True)
        btn_row.setFixedHeight(60)
        btn_row.setStyleSheet("border: none;")
        bottom_layout = QHBoxLayout(btn_row)
        bottom_layout.setContentsMargins(12, 2, 12, 2)
        bottom_layout.setSpacing(2)

        BOTTOM_BTN_STYLE = """
            QToolButton {
                background: transparent;
                color: #3a2000;
                border: none;
                border-radius: 6px;
                padding: 4px 10px;
                font-size: 9pt;
            }
            QToolButton:hover { background: rgba(180, 130, 60, 100); }
            QToolButton:pressed { background: rgba(140, 95, 30, 150); }
        """

        def _mk_bottom_btn(icon_key, text, slot=None):
            from PySide6.QtWidgets import QToolButton
            btn = QToolButton()
            btn.setText(text)
            btn.setIcon(_lucide_icon(icon_key))
            btn.setIconSize(QSize(22, 22))
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setAutoRaise(True)
            btn.setStyleSheet(BOTTOM_BTN_STYLE)
            if slot:
                btn.clicked.connect(slot)
            return btn

        self.btn_move = _mk_bottom_btn("move", tr("btn_move"), self._show_move_menu)
        bottom_layout.addWidget(self.btn_move)
        bottom_layout.addWidget(_mk_bottom_btn("page", tr("btn_page"), self._toggle_page_list))
        bottom_layout.addWidget(_mk_bottom_btn("bookmark", tr("btn_bookmark"), self._toggle_bookmark_list))
        self.btn_slideshow = _mk_bottom_btn("play", tr("btn_slideshow"), self._show_slideshow_menu)
        bottom_layout.addWidget(self.btn_slideshow)

        bottom_layout.addStretch()

        bottom_layout.addWidget(_mk_bottom_btn("maximize", tr("btn_fit"), self.cycle_fit_mode))
        _rd = self._viewer_settings.get("reading_direction", "rtl")
        self.btn_reading_dir = _mk_bottom_btn(
            "flip-horizontal",
            tr("reading_rtl") if _rd == "rtl" else tr("reading_ltr"),
            self._toggle_reading_direction,
        )
        bottom_layout.addWidget(self.btn_reading_dir)

        bottom_outer.addWidget(btn_row)

        # ---- 下段: ページサムネイル一覧 ----
        self.thumb_scroll = QScrollArea()
        self.thumb_scroll.setFrameShape(QFrame.NoFrame)
        self.thumb_scroll.setFocusPolicy(Qt.NoFocus)
        self.thumb_scroll.setWidgetResizable(False)
        self.thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumb_scroll.setFixedHeight(160)
        self.thumb_scroll.setAttribute(Qt.WA_NoSystemBackground, True)
        self.thumb_scroll.setAttribute(Qt.WA_TranslucentBackground, True)
        self.thumb_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:horizontal {
                background: transparent;
                height: 8px;
                margin: 0px 4px;
            }
            QScrollBar::handle:horizontal {
                background: rgba(120, 80, 30, 150);
                border-radius: 4px;
                min-width: 40px;
            }
            QScrollBar::handle:horizontal:hover {
                background: rgba(140, 95, 30, 200);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        self.thumb_scroll.viewport().setAttribute(Qt.WA_NoSystemBackground, True)
        self.thumb_scroll.viewport().setAttribute(Qt.WA_TranslucentBackground, True)
        self.thumb_scroll.viewport().setStyleSheet("background: transparent;")

        self.thumb_container = WoodOverlayWidget(wood_pixmap)
        self.thumb_container.setStyleSheet("border: none;")
        self.thumb_layout = QHBoxLayout(self.thumb_container)
        self.thumb_layout.setContentsMargins(8, 4, 8, 8)
        self.thumb_layout.setSpacing(4)
        self.thumb_layout.setAlignment(Qt.AlignRight)  # 右端=1ページ目（右綴じ）

        self.thumb_scroll.setWidget(self.thumb_container)
        bottom_outer.addWidget(self.thumb_scroll)
        self.bottom_overlay.setVisible(False)

        # ---- ページリスト サイドパネル（左側、「ページ」ボタンでトグル） ----
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        self.page_list_panel = WoodOverlayWidget(wood_pixmap, central, border_right=True)
        self.page_list_panel.setStyleSheet("border: none;")
        page_list_layout = QVBoxLayout(self.page_list_panel)
        page_list_layout.setContentsMargins(0, 0, 0, 0)
        page_list_layout.setSpacing(0)

        self.page_list_widget = QListWidget()
        self.page_list_widget.setFocusPolicy(Qt.NoFocus)
        self.page_list_widget.setFrameShape(QFrame.NoFrame)
        self.page_list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                color: #3a2000;
                font-size: 10pt;
                border: none;
            }
            QListWidget::item {
                padding: 6px 12px;
                border-bottom: 1px solid rgba(120, 80, 30, 40);
            }
            QListWidget::item:selected {
                background: rgba(120, 200, 120, 130);
                color: #3a2000;
            }
            QListWidget::item:hover {
                background: rgba(180, 130, 60, 60);
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: rgba(120, 80, 30, 150);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.page_list_widget.itemClicked.connect(self._on_page_list_clicked)
        page_list_layout.addWidget(self.page_list_widget)

        self.page_list_panel.setVisible(False)
        self._page_list_visible = False

        # ---- しおり一覧 サイドパネル（左側、「しおり」ボタンでトグル） ----
        self.bookmark_list_panel = WoodOverlayWidget(wood_pixmap, central, border_right=True)
        self.bookmark_list_panel.setStyleSheet("border: none;")
        bookmark_layout = QVBoxLayout(self.bookmark_list_panel)
        bookmark_layout.setContentsMargins(0, 4, 0, 0)
        bookmark_layout.setSpacing(0)

        # ピン留めアイコン（パネルの目印）
        pin_label = QLabel()
        pin_label.setPixmap(_lucide_pixmap_for_thumb("pin", "#3a2000", 18))
        pin_label.setFixedHeight(22)
        pin_label.setContentsMargins(8, 0, 0, 0)
        pin_label.setStyleSheet("background: transparent;")
        bookmark_layout.addWidget(pin_label)

        self.bookmark_list_widget = QListWidget()
        self.bookmark_list_widget.setFocusPolicy(Qt.NoFocus)
        self.bookmark_list_widget.setFrameShape(QFrame.NoFrame)
        self.bookmark_list_widget.setStyleSheet("""
            QListWidget {
                background: transparent;
                color: #3a2000;
                font-size: 10pt;
                border: none;
            }
            QListWidget::item {
                padding: 6px 12px;
                border-bottom: 1px solid rgba(120, 80, 30, 40);
            }
            QListWidget::item:selected {
                background: rgba(120, 200, 120, 130);
                color: #3a2000;
            }
            QListWidget::item:hover {
                background: rgba(180, 130, 60, 60);
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
            }
            QScrollBar::handle:vertical {
                background: rgba(120, 80, 30, 150);
                border-radius: 4px;
                min-height: 30px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.bookmark_list_widget.itemClicked.connect(self._on_bookmark_list_clicked)
        bookmark_layout.addWidget(self.bookmark_list_widget)

        self.bookmark_list_panel.setVisible(False)
        self._bookmark_list_visible = False

        self._thumb_widgets: dict[int, QWidget] = {}  # index -> サムネイルウィジェット

        # 互換用ダミー（旧ツールバー要素の参照を残しているコード向け）
        self.act_prev = QPushButton()
        self.act_next = QPushButton()
        self.act_fit = QPushButton()
        self.status_label = QLabel("")
        self.act_prev.setVisible(False)
        self.act_next.setVisible(False)
        self.act_fit.setVisible(False)
        self.status_label.setVisible(False)

        self._central_stack = central
        self._set_loading(True)   # 最初はローディング表示

    def _set_loading(self, loading: bool):
        self._central_stack.setCurrentIndex(0 if loading else 1)
        self.act_prev.setEnabled(not loading)
        self.act_next.setEnabled(not loading)
        self._reposition_overlays()
        if not loading:
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, self.setFocus)

    # ------------------------------------------------------------------ #
    # ページ表示
    # ------------------------------------------------------------------ #

    def _refresh_thumb_cell(self, index: int):
        """指定ページのサムネイルセルだけを再生成して置き換える（軽量更新）"""
        old_cell = self._thumb_widgets.get(index)
        if old_cell is None:
            return
        new_cell = self._make_thumb_cell(index)
        layout_index = self.thumb_layout.indexOf(old_cell)
        if layout_index == -1:
            return
        self.thumb_layout.removeWidget(old_cell)
        old_cell.deleteLater()
        self.thumb_layout.insertWidget(layout_index, new_cell)
        self._thumb_widgets[index] = new_cell
        self._apply_thumb_highlight_styles()

    def _stop_strip_worker(self):
        """サムネイルストリップワーカーを安全に停止する"""
        if self._strip_worker:
            self._strip_worker.cancel()
            try:
                self._strip_worker.thumb_ready.disconnect()
            except RuntimeError:
                pass
        if self._strip_thread is not None:
            try:
                self._strip_thread.quit()
                self._strip_thread.wait(2000)
            except RuntimeError:
                pass
        self._strip_worker = None
        self._strip_thread = None

    def _build_thumbnail_strip(self):
        """下部のページサムネイル一覧を構築する（画像はバックグラウンドで非同期ロード）"""
        # 前回のワーカーを停止
        self._stop_strip_worker()

        while self.thumb_layout.count() > 0:
            item = self.thumb_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._thumb_widgets = {}
        self._thumb_labels = {}

        total = len(self.pages)
        from settings import load_settings as _ls
        _rtl = _ls().get("reading_direction", "rtl") == "rtl"
        self.thumb_layout.setAlignment(Qt.AlignRight if _rtl else Qt.AlignLeft)
        for i in (reversed(range(total)) if _rtl else range(total)):
            cell = self._make_thumb_cell(i)
            self.thumb_layout.addWidget(cell)
            self._thumb_widgets[i] = cell

        self.thumb_container.adjustSize()
        # 明示的に合計幅を計算してセット
        cell_w = 90
        spacing = 4
        margins_h = 16  # left+right (8+8)
        total_w = total * cell_w + max(0, total - 1) * spacing + margins_h
        viewport_w = self.bottom_overlay.width() - 16  # margins分を引く
        if viewport_w <= 0:
            viewport_w = max(self.width(), 800) - 16
        self.thumb_container.setFixedSize(max(total_w, viewport_w), 150)
        self._update_thumb_highlight()
        # 現在ページ（しおり位置 or 1ページ目）のサムネイルが見える位置へスクロール
        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, self._scroll_thumb_to_current)
        _QTimer.singleShot(100, self._scroll_thumb_to_current)

        # サムネイル画像をバックグラウンドで非同期ロード（UIスレッドをブロックしない）
        if self.pages:
            worker = ThumbStripWorker(
                list(self.pages), self._page_type, dict(self._page_rotations)
            )
            thread = QThread(self)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.thumb_ready.connect(self._on_strip_thumb_ready)
            self._strip_worker = worker
            self._strip_thread = thread
            thread.start()

    def _on_strip_thumb_ready(self, index: int, data: bytes, w: int, h: int):
        """バックグラウンドから届いたサムネイル画像をラベルに反映する"""
        label = self._thumb_labels.get(index)
        if label is None:
            return
        from PySide6.QtGui import QTransform
        qimg = QImage(data, w, h, w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        angle = self._page_rotations.get(index, 0)
        if angle:
            pix = pix.transformed(QTransform().rotate(angle), Qt.SmoothTransformation)
        label.setPixmap(pix)

    def _scroll_thumb_to_current(self):
        """現在ページのサムネイルが見えるようにスクロールする"""
        cell = self._thumb_widgets.get(self.current_index)
        if cell is None:
            return
        sb = self.thumb_scroll.horizontalScrollBar()
        viewport_w = self.thumb_scroll.viewport().width()
        # セルの中心がビューポートの中心に来るようにスクロール
        cell_center = cell.x() + cell.width() // 2
        target = cell_center - viewport_w // 2
        sb.setValue(max(sb.minimum(), min(target, sb.maximum())))

    def _make_thumb_cell(self, index: int) -> QWidget:
        """1ページ分のサムネイルセル（ページ番号 + 画像 + ファイル名）を作る"""
        cell = QFrame()
        cell.setFixedSize(90, 150)
        cell.setStyleSheet("background: transparent;")
        v = QVBoxLayout(cell)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(1)

        # ページ番号（桁数は総ページ数の桁数に合わせる: 9頁以下=1桁, 100頁以下=3桁, 10000頁=5桁など）
        total = len(self.pages)
        digits = len(str(total))
        page_no_label = QLabel(f"{index + 1:0{digits}d}")
        page_no_label.setFixedHeight(14)
        page_no_label.setAlignment(Qt.AlignCenter)
        page_no_label.setStyleSheet("color: #3a2000; font-size: 8pt; background: transparent;")
        v.addWidget(page_no_label)

        thumb_label = QLabel()
        thumb_label.setFixedSize(86, 108)
        thumb_label.setAlignment(Qt.AlignCenter)
        thumb_label.setStyleSheet("background: rgba(0,0,0,20); border-radius: 3px;")
        self._thumb_labels[index] = thumb_label  # バックグラウンドワーカーから更新する
        v.addWidget(thumb_label, alignment=Qt.AlignCenter)

        # しおりアイコン（しおりが付いている場合のみ、画像左上に重ねて表示）
        if index in self._bookmarked_pages:
            bookmark_icon = QLabel(thumb_label)
            bookmark_icon.setPixmap(_lucide_pixmap_for_thumb("bookmark", "#cc3333", 18))
            bookmark_icon.move(2, 2)
            bookmark_icon.setStyleSheet("background: transparent;")
            bookmark_icon.show()

        name = self._page_names[index] if index < len(self._page_names) else f"{index+1:04d}"
        name_label = QLabel(name)
        name_label.setFixedHeight(18)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("color: #3a2000; font-size: 8pt; background: transparent;")
        name_label.setWordWrap(False)
        v.addWidget(name_label)

        cell.mousePressEvent = lambda ev, idx=index, c=cell: self._on_thumb_cell_clicked(ev, idx, c)

        return cell

    def _on_thumb_cell_clicked(self, ev, index: int, cell: QWidget):
        """サムネイルクリック: 左クリックでページ移動、右クリックで画像オプション表示"""
        if ev.button() == Qt.RightButton:
            self._show_image_options_menu(index, cell)
        else:
            self._goto_page_from_thumb(index)

    def _show_image_options_menu(self, index: int, cell: QWidget):
        """サムネイル右クリック: 「しおりをはさむ」「画像の回転」のみのオプションメニュー"""
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #fdf6ec;
                color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 120);
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 28px;
                font-size: 10.5pt;
            }
            QMenu::item:selected {
                background: rgba(180, 130, 60, 100);
                border-radius: 4px;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(120, 80, 30, 80);
                margin: 4px 8px;
            }
        """)

        is_bookmarked = index in self._bookmarked_pages
        bookmark_label = tr("img_bm_remove") if is_bookmarked else tr("img_bm_add")
        act_bookmark = menu.addAction(bookmark_label)

        menu.addSeparator()
        act_rotate_left = menu.addAction(tr("img_rot_left"))
        act_rotate_180 = menu.addAction(tr("img_rot_180"))
        act_rotate_right = menu.addAction(tr("img_rot_right"))
        act_rotate_reset = menu.addAction(tr("img_rot_reset"))

        act_bookmark.triggered.connect(lambda: self._toggle_bookmark(index, cell))
        act_rotate_left.triggered.connect(lambda: self._rotate_page(index, -90, cell))
        act_rotate_180.triggered.connect(lambda: self._rotate_page(index, 180, cell))
        act_rotate_right.triggered.connect(lambda: self._rotate_page(index, 90, cell))
        act_rotate_reset.triggered.connect(lambda: self._rotate_page(index, None, cell))

        pos = cell.mapToGlobal(cell.rect().topLeft())
        menu_height = menu.sizeHint().height()
        from PySide6.QtCore import QPoint
        menu.exec(pos - QPoint(0, menu_height))

    def _ask_text_input(self, title: str, label: str, default_text: str) -> str | None:
        """
        テキスト入力ダイアログを表示する。

        venv環境のPySide6ではIME(日本語入力)がフリーズ/動作しない問題があるため、
        zenityが利用可能ならそちらを使う（別プロセスのGTKダイアログなので
        システムのIME設定がそのまま使える）。
        zenityが無い場合はQInputDialogにフォールバック（日本語入力不可）。

        戻り値: 入力文字列。キャンセル時はNone。
        """
        import shutil
        if shutil.which("zenity"):
            import subprocess
            try:
                proc = subprocess.run(
                    ["zenity", "--entry",
                     "--title", title,
                     "--text", label,
                     "--entry-text", default_text],
                    capture_output=True, text=True
                )
                if proc.returncode == 0:
                    return proc.stdout.rstrip("\n")
                return None  # キャンセル
            except Exception as e:
                print(f"zenity呼び出しエラー: {e}")
                # フォールバックへ

        # zenityが無い場合のフォールバック（日本語入力は不可な可能性あり）
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, title, label, text=default_text)
        if not ok:
            return None
        return text

    def _toggle_bookmark(self, index: int, cell: QWidget):
        """しおりの付け外しをトグルする。付ける場合はラベルを入力させる"""
        if index in self._bookmarked_pages:
            del self._bookmarked_pages[index]
            save_bookmarks(self.file_path, self._bookmarked_pages)
            self._refresh_thumb_cell(index)
            if self._bookmark_list_visible:
                self._build_bookmark_list()
            return

        # しおりを付ける: ラベル入力ダイアログを表示
        # デフォルト値はそのページのファイル名（拡張子なし）
        if index < len(self._page_names):
            default_label = Path(self._page_names[index]).stem
        else:
            default_label = f"{index + 1}"

        label = self._ask_text_input(tr("bm_dlg_title"), tr("bm_dlg_label"), default_label)
        if label is None:
            return  # キャンセル時はしおりを付けない

        self._bookmarked_pages[index] = label
        save_bookmarks(self.file_path, self._bookmarked_pages)
        # サムネイル一覧はこのページだけ再生成してしおりアイコンを反映
        self._refresh_thumb_cell(index)
        if self._bookmark_list_visible:
            self._build_bookmark_list()

    def _rotate_page(self, index: int, delta, cell: QWidget):
        """ページを回転する。delta=Noneの場合はリセット(0度)。
        delta=±90/180 の場合は現在の角度に加算し0-359に正規化する。"""
        if delta is None:
            self._page_rotations.pop(index, None)
        else:
            current = self._page_rotations.get(index, 0)
            new_angle = (current + delta) % 360
            if new_angle == 0:
                self._page_rotations.pop(index, None)
            else:
                self._page_rotations[index] = new_angle
        save_rotations(self.file_path, self._page_rotations)

        # 表示中ページなら即時反映
        if index == self.current_index or (
            self.pages_per_screen == 2 and index == self.current_index + 1
        ):
            self.zoom = 1.0
            self._show_page()

        # サムネイル一覧はこのページだけ再生成して反映
        self._refresh_thumb_cell(index)

    def _goto_page_from_thumb(self, index: int):
        if 0 <= index < len(self.pages):
            self.current_index = index
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def _apply_thumb_highlight_styles(self):
        """各サムネイルセルにハイライト色を適用する（スクロールは行わない）"""
        active = {self.current_index}
        if self.pages_per_screen == 2 and self.current_index + 1 < len(self.pages):
            active.add(self.current_index + 1)
        for i, cell in self._thumb_widgets.items():
            if i in active:
                cell.setStyleSheet(
                    "QFrame { background: rgba(120, 200, 120, 130); border-radius: 4px; }"
                    "QLabel { background: transparent; }"
                )
            else:
                cell.setStyleSheet(
                    "QFrame { background: transparent; }"
                    "QLabel { background: transparent; }"
                )

    def _update_thumb_highlight(self):
        """現在表示中のページのサムネイルを強調表示し、スクロール追従も行う"""
        self._apply_thumb_highlight_styles()
        # 現在ページのサムネイルが見えるようスクロール追従
        if self._thumb_widgets:
            self._scroll_thumb_to_current()
        # ページ一覧パネルが表示中なら現在ページに追従
        if self._page_list_visible:
            self._scroll_page_list_to_current()

    def _get_pixmap(self, index: int) -> QPixmap | None:
        if not self.pages or not (0 <= index < len(self.pages)):
            return None
        item = self.pages[index]
        try:
            if self._page_type == "archive":
                img = safe_open_image(item)           # bytes
            elif self._page_type == "archive_cached":
                img = safe_open_image_from_path(item) # Path（ディスクキャッシュから読む）
            else:
                img = safe_open_image_from_path(item) # Path（画像フォルダ）
            if img is None:
                return None
            pix = pil_to_qpixmap(img)
            angle = self._page_rotations.get(index, 0)
            if angle:
                from PySide6.QtGui import QTransform
                pix = pix.transformed(QTransform().rotate(angle), Qt.SmoothTransformation)
            return pix
        except Exception as e:
            print(f"ページ読み込みエラー index={index}: {e}")
            return None

    def _show_page(self):
        if not self.pages:
            self.image_label.setText(tr("no_images"))
            return

        pixmap = self._get_pixmap(self.current_index)
        if pixmap is None:
            self.image_label.setText(tr("img_load_error"))
            return

        # 2ページ見開き表示: current_index(右) + current_index+1(左) を横に合成
        if self.pages_per_screen == 2 and self.current_index + 1 < len(self.pages):
            next_pix = self._get_pixmap(self.current_index + 1)
            if next_pix is not None and not next_pix.isNull():
                pixmap = self._compose_spread(pixmap, next_pix)

        self._original_pixmap = pixmap
        self._apply_display()
        self._update_status()

    def _compose_spread(self, right_pix: QPixmap, left_pix: QPixmap) -> QPixmap:
        """2ページを見開き（右→左）に合成する。
        日本の漫画は右綴じなので、若いページ(current)が右側に来る。
        高さを揃えて横に並べる。"""
        from PySide6.QtGui import QPainter
        h = max(right_pix.height(), left_pix.height())
        # 高さを揃えるためスケール
        if right_pix.height() != h:
            right_pix = right_pix.scaledToHeight(h, Qt.SmoothTransformation)
        if left_pix.height() != h:
            left_pix = left_pix.scaledToHeight(h, Qt.SmoothTransformation)
        w = right_pix.width() + left_pix.width()
        combined = QPixmap(w, h)
        combined.fill(Qt.transparent)
        p = QPainter(combined)
        # 左側に次ページ、右側に現在ページ
        p.drawPixmap(0, 0, left_pix)
        p.drawPixmap(left_pix.width(), 0, right_pix)
        p.end()
        return combined

    def _apply_display(self):
        if self._original_pixmap is None:
            return
        pixmap = self._original_pixmap
        vw = self.scroll_area.viewport().width()
        vh = self.scroll_area.viewport().height()
        pw, ph = pixmap.width(), pixmap.height()

        if self.fit_mode == self.FIT_WINDOW:
            scale = min(vw / pw, vh / ph) if pw > 0 and ph > 0 else 1.0
        elif self.fit_mode == self.FIT_WIDTH:
            scale = vw / pw if pw > 0 else 1.0
        elif self.fit_mode == self.FIT_HEIGHT:
            scale = vh / ph if ph > 0 else 1.0
        else:
            scale = 1.0

        scale *= self.zoom
        new_w = max(1, int(pw * scale))
        new_h = max(1, int(ph * scale))
        scaled = pixmap.scaled(new_w, new_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)

    def _update_status(self):
        total = len(self.pages)
        idx = self.current_index + 1
        # アーカイブ内のファイル名を取得
        if self._page_names and self.current_index < len(self._page_names):
            inner_name = self._page_names[self.current_index]
        elif self._page_type == "files" and self.pages:
            inner_name = self.pages[self.current_index].name
        else:
            inner_name = f"{self.current_index + 1:04d}"
        # 上部オーバーレイにアーカイブ名と内部ファイル名、キャッシュ状態を表示
        archive_name = self.file_path.name
        cache_status = tr("cache_caching") if self._caching else tr("cache_done")
        from page_cache import has_cached_pages
        if not self._caching and not has_cached_pages(self.file_path):
            cache_status = ""
        self.toolbar_label.setText(f"{archive_name}  ／  {inner_name}{cache_status}")
        status_name = f"  |  {inner_name}" if inner_name else ""
        self.status_label.setText(
            f"ページ {idx} / {total}{status_name}    ズーム: {int(self.zoom * 100)}%    モード: {self.fit_mode}"
        )

    # ------------------------------------------------------------------ #
    # ページ操作
    # ------------------------------------------------------------------ #

    def next_page(self):
        # ストリーミング中は届いているページ数 or 全体の最大まで進める
        step = self.pages_per_screen
        max_index = len(self.pages) - 1
        if self.current_index < max_index:
            self.current_index = min(self.current_index + step, max_index)
            self.zoom = 1.0
            # ページデータが届いていれば表示、まだなら待機（_on_page_readyで表示される）
            if self.current_index < len(self.pages) and self.pages[self.current_index]:
                self._show_page()
            else:
                self.image_label.setText("読み込み中...")
            self._update_thumb_highlight()

    def prev_page(self):
        step = self.pages_per_screen
        if self.current_index > 0:
            self.current_index = max(self.current_index - step, 0)
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def zoom_in(self):
        self.zoom = min(self.zoom * 1.25, 8.0)
        self._apply_display()
        self._update_status()

    def zoom_out(self):
        self.zoom = max(self.zoom / 1.25, 0.1)
        self._apply_display()
        self._update_status()

    def cycle_fit_mode(self):
        modes = [self.FIT_WINDOW, self.FIT_WIDTH, self.FIT_HEIGHT, self.FIT_ORIGIN]
        self.fit_mode = modes[(modes.index(self.fit_mode) + 1) % len(modes)]
        self.act_fit.setText(self.fit_mode)
        self.zoom = 1.0
        self._apply_display()
        self._update_status()

    # ------------------------------------------------------------------ #
    # 上部オーバーレイ操作
    # ------------------------------------------------------------------ #

    def open_containing_folder(self):
        """画像（圧縮ファイル）のある場所をファイルマネージャーで開く"""
        import subprocess
        folder = str(self.file_path.parent)
        try:
            subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            print(f"フォルダを開けませんでした: {e}")

    def back_to_shelf_requested_slot(self):
        """「本棚」ボタン: 親（BookshelfWindow）に本棚へ戻ることを通知"""
        self.back_to_shelf_requested.emit()

    def toggle_fullscreen(self):
        """完全なフルスクリーン表示に切り替える（トグル）"""
        # inline埋め込みの場合は親ウィンドウをフルスクリーン化
        target = self.window()
        if target.isFullScreen():
            # フルスクリーン化前が最大化だった場合は最大化状態に戻す
            if getattr(target, "_was_maximized_before_fullscreen", False):
                target.showMaximized()
            else:
                target.showNormal()
        else:
            target._was_maximized_before_fullscreen = target.isMaximized()
            target.showFullScreen()
        # フルスクリーン中もホイール/キー操作はwheelEvent/keyPressEventで継続動作
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._reposition_overlays)

    def _show_move_menu(self):
        """「移動...」ボタン: ポップアップメニューを表示"""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #fdf6ec;
                color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 120);
                padding: 6px;
            }
            QMenu::item {
                padding: 10px 32px;
                font-size: 11pt;
            }
            QMenu::item:selected {
                background: rgba(180, 130, 60, 100);
                border-radius: 4px;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(120, 80, 30, 80);
                margin: 4px 8px;
            }
        """)

        act_next_book = menu.addAction(tr("move_next_book"))
        act_prev_book = menu.addAction(tr("move_prev_book"))
        menu.addSeparator()
        act_first = menu.addAction(tr("move_first"))
        act_last = menu.addAction(tr("move_last"))
        act_goto = menu.addAction(tr("move_goto"))

        act_next_book.triggered.connect(lambda: self.open_sibling_requested.emit(1))
        act_prev_book.triggered.connect(lambda: self.open_sibling_requested.emit(-1))
        act_first.triggered.connect(self.goto_first_page)
        act_last.triggered.connect(self.goto_last_page)
        act_goto.triggered.connect(self._show_goto_page_dialog)

        # ボタンの上にメニューを表示
        btn = self.btn_move
        pos = btn.mapToGlobal(btn.rect().topLeft())
        menu_height = menu.sizeHint().height()
        from PySide6.QtCore import QPoint
        menu.exec(pos - QPoint(0, menu_height))

    def _show_slideshow_menu(self):
        """「スライドショー」ボタン: 開始／設定のポップアップメニューを表示"""
        from PySide6.QtWidgets import QMenu
        from PySide6.QtCore import QPoint
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #fdf6ec;
                color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 120);
                padding: 6px;
            }
            QMenu::item {
                padding: 10px 32px;
                font-size: 11pt;
            }
            QMenu::item:selected {
                background: rgba(180, 130, 60, 100);
                border-radius: 4px;
            }
        """)

        act_start  = menu.addAction(tr("ss_start"))
        act_config = menu.addAction(tr("ss_settings"))

        act_start.triggered.connect(self._slideshow_start)
        act_config.triggered.connect(self._slideshow_config)

        btn = self.btn_slideshow
        pos = btn.mapToGlobal(btn.rect().topLeft())
        menu_height = menu.sizeHint().height()
        menu.exec(pos - QPoint(0, menu_height))

    def _slideshow_start(self):
        """スライドショー開始: 現在のページから設定に従って自動ページ送りを開始する"""
        from PySide6.QtCore import QTimer as _QTimer
        from settings import load_settings
        if not self.pages:
            return
        self._slideshow_stop()
        s = load_settings()
        interval_ms = max(200, int(s.get("slideshow_interval", 3.0) * 1000))
        self._slideshow_timer = _QTimer(self)
        self._slideshow_timer.setInterval(interval_ms)
        self._slideshow_timer.timeout.connect(self._slideshow_advance)
        self._slideshow_timer.start()
        self._slideshow_running = True
        # オーバーレイメニューを閉じる
        self._overlay_visible = False
        self.top_overlay.setVisible(False)
        self.bottom_overlay.setVisible(False)
        if self._page_list_visible:
            self._page_list_visible = False
            self.page_list_panel.setVisible(False)
        if self._bookmark_list_visible:
            self._bookmark_list_visible = False
            self.bookmark_list_panel.setVisible(False)

    def _slideshow_stop(self):
        """スライドショー停止"""
        if self._slideshow_timer is not None:
            self._slideshow_timer.stop()
            self._slideshow_timer = None
        self._slideshow_running = False
        if self._anim_group is not None:
            try:
                self._anim_group.stop()
            except Exception:
                pass
            self._anim_group = None
        for lbl in self._anim_labels:
            try:
                lbl.deleteLater()
            except Exception:
                pass
        self._anim_labels.clear()

    def _slideshow_advance(self):
        """タイマー発火ごとに次ページへ進む。アニメーション中はスキップ。"""
        if self._anim_group is not None:
            return
        from settings import load_settings
        s = load_settings()
        effect      = s.get("slideshow_effect", "none")
        duration_ms = max(50, int(s.get("slideshow_effect_duration", 1.0) * 1000))
        end_action  = s.get("slideshow_end_action", "stop")

        next_index = self.current_index + self.pages_per_screen
        if next_index >= len(self.pages):
            if end_action == "stop":
                self._slideshow_stop()
                return
            elif end_action == "first":
                next_index = 0
            elif end_action == "next_book":
                self._slideshow_stop()
                self.open_sibling_requested.emit(1)
                return

        if effect == "none":
            self.current_index = next_index
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()
        else:
            self._slideshow_transition(next_index, effect, duration_ms)

    def _get_display_pixmap(self, index: int) -> "QPixmap | None":
        """表示用pixmapを返す。pages_per_screen==2 のとき見開き合成を行う。"""
        pixmap = self._get_pixmap(index)
        if pixmap is None:
            return None
        if self.pages_per_screen == 2 and index + 1 < len(self.pages):
            next_pix = self._get_pixmap(index + 1)
            if next_pix is not None and not next_pix.isNull():
                pixmap = self._compose_spread(pixmap, next_pix)
        return pixmap

    def _slideshow_transition(self, next_index: int, effect: str, duration_ms: int):
        """アニメーション付きページ遷移"""
        from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect
        from PySide6.QtCore import QPropertyAnimation, QRect, QParallelAnimationGroup

        central = self._central_stack
        w = central.width()
        h = central.height()
        view_rect = QRect(0, 0, w, h)

        def _make_label(index: int, x: int = 0) -> QLabel:
            lbl = QLabel(central)
            lbl.setGeometry(QRect(x, 0, w, h))
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background: #1a1a1a; border: none;")
            pix = self._get_display_pixmap(index)  # 見開き合成対応
            if pix:
                lbl.setPixmap(pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            lbl.show()
            lbl.raise_()
            return lbl

        cur_index = self.current_index
        self.current_index = next_index

        if effect in ("slide_in", "slide_out"):
            # slide_in  : 新ページが右から入ってきて現ページが左へ出る
            # slide_out : 現ページが右へ出て新ページが左から入ってくる
            start_x_next = w  if effect == "slide_in"  else -w
            end_x_cur    = -w if effect == "slide_in"  else  w

            lbl_cur  = _make_label(cur_index,  0)
            lbl_next = _make_label(next_index, start_x_next)
            self._anim_labels = [lbl_cur, lbl_next]

            anim_cur = QPropertyAnimation(lbl_cur, b"geometry")
            anim_cur.setDuration(duration_ms)
            anim_cur.setStartValue(view_rect)
            anim_cur.setEndValue(QRect(end_x_cur, 0, w, h))

            anim_next = QPropertyAnimation(lbl_next, b"geometry")
            anim_next.setDuration(duration_ms)
            anim_next.setStartValue(QRect(start_x_next, 0, w, h))
            anim_next.setEndValue(view_rect)

        elif effect == "dissolve":
            lbl_cur  = _make_label(cur_index)
            lbl_next = _make_label(next_index)
            self._anim_labels = [lbl_cur, lbl_next]

            fx_cur  = QGraphicsOpacityEffect(lbl_cur)
            fx_next = QGraphicsOpacityEffect(lbl_next)
            lbl_cur.setGraphicsEffect(fx_cur)
            lbl_next.setGraphicsEffect(fx_next)
            fx_cur.setOpacity(1.0)
            fx_next.setOpacity(0.0)

            anim_cur = QPropertyAnimation(fx_cur, b"opacity")
            anim_cur.setDuration(duration_ms)
            anim_cur.setStartValue(1.0)
            anim_cur.setEndValue(0.0)

            anim_next = QPropertyAnimation(fx_next, b"opacity")
            anim_next.setDuration(duration_ms)
            anim_next.setStartValue(0.0)
            anim_next.setEndValue(1.0)

        else:
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()
            return

        group = QParallelAnimationGroup(self)
        group.addAnimation(anim_cur)
        group.addAnimation(anim_next)

        def _on_done():
            for lbl in self._anim_labels:
                try:
                    lbl.deleteLater()
                except Exception:
                    pass
            self._anim_labels.clear()
            self._anim_group = None
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

        group.finished.connect(_on_done)
        self._anim_group = group
        group.start()

    def _slideshow_config(self):
        """スライドショー設定ダイアログを表示する"""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QDoubleSpinBox, QComboBox, QPushButton, QFrame
        )
        from settings import load_settings, save_settings

        s = load_settings()

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("ss_dlg_title"))
        dlg.setMinimumWidth(440)
        dlg.setStyleSheet("""
            QDialog { background: #f5e8c8; }
            QLabel  { color: #3a2000; background: transparent; font-size: 11pt; }
            QDoubleSpinBox, QComboBox {
                background: #fdf6ec; color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 150);
                border-radius: 3px; padding: 4px 8px; font-size: 11pt;
            }
            QComboBox::drop-down { border: none; width: 20px; }
            QComboBox QAbstractItemView {
                background: #fdf6ec; color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 150);
                selection-background-color: rgba(180, 130, 60, 160);
                selection-color: #3a2000;
            }
            QPushButton {
                background: #e8d5b5; color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 150);
                border-radius: 4px; padding: 8px 28px; font-size: 11pt;
            }
            QPushButton:hover   { background: #dcc49a; }
            QPushButton:pressed { background: #cdb080; }
        """)

        vbox = QVBoxLayout(dlg)
        vbox.setContentsMargins(28, 20, 28, 20)
        vbox.setSpacing(14)

        LABEL_W = 175

        def _field_row(label_text, widget, suffix=None):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(LABEL_W)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(lbl)
            row.addSpacing(10)
            row.addWidget(widget)
            if suffix:
                row.addSpacing(4)
                row.addWidget(QLabel(suffix))
            row.addStretch()
            return row

        # ---- ページあたりの時間 ----
        spin_interval = QDoubleSpinBox()
        spin_interval.setRange(0.5, 60.0)
        spin_interval.setSingleStep(0.5)
        spin_interval.setDecimals(1)
        spin_interval.setFixedWidth(90)
        spin_interval.setValue(s.get("slideshow_interval", 3.0))
        vbox.addLayout(_field_row(tr("ss_interval"), spin_interval, tr("ss_sec")))

        # ---- 最後に達したときの動作 ----
        combo_end = QComboBox()
        combo_end.addItems([tr("ss_end_stop"), tr("ss_end_first"), tr("ss_end_next_book")])
        combo_end.setFixedWidth(180)
        end_map = {"stop": 0, "first": 1, "next_book": 2}
        combo_end.setCurrentIndex(end_map.get(s.get("slideshow_end_action", "stop"), 0))
        vbox.addLayout(_field_row(tr("ss_end_action"), combo_end))

        # ---- セパレータ ----
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("QFrame { background: rgba(120,80,30,100); max-height: 1px; border: none; }")
        vbox.addSpacing(2)
        vbox.addWidget(sep)
        vbox.addSpacing(2)

        # ---- ページ切り替え効果セクション ----
        section_lbl = QLabel(tr("ss_effects_section"))
        section_lbl.setStyleSheet(
            "font-size: 11pt; font-weight: bold; color: #3a2000; background: transparent;"
        )
        vbox.addWidget(section_lbl)

        # 効果
        combo_effect = QComboBox()
        combo_effect.addItems([tr("ss_effect_none"), tr("ss_effect_slide_in"),
                               tr("ss_effect_slide_out"), tr("ss_effect_dissolve")])
        combo_effect.setFixedWidth(240)
        effect_map = {"none": 0, "slide_in": 1, "slide_out": 2, "dissolve": 3}
        combo_effect.setCurrentIndex(effect_map.get(s.get("slideshow_effect", "none"), 0))
        vbox.addLayout(_field_row(tr("ss_effect"), combo_effect))

        # 長さ
        spin_duration = QDoubleSpinBox()
        spin_duration.setRange(0.1, 5.0)
        spin_duration.setSingleStep(0.1)
        spin_duration.setDecimals(1)
        spin_duration.setFixedWidth(90)
        spin_duration.setValue(s.get("slideshow_effect_duration", 1.0))
        vbox.addLayout(_field_row(tr("ss_duration"), spin_duration, tr("ss_sec")))

        # 効果が「なし」のとき長さを無効化
        def _on_effect_changed(idx):
            spin_duration.setEnabled(idx > 0)
        combo_effect.currentIndexChanged.connect(_on_effect_changed)
        _on_effect_changed(combo_effect.currentIndex())

        vbox.addSpacing(10)

        # ---- 開始／停止ボタン ----
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_start = QPushButton(tr("ss_btn_start"))
        btn_row.addWidget(btn_start)
        btn_row.addStretch()
        vbox.addLayout(btn_row)

        def _save():
            end_vals    = ["stop", "first", "next_book"]
            effect_vals = ["none", "slide_in", "slide_out", "dissolve"]
            s["slideshow_interval"]        = spin_interval.value()
            s["slideshow_end_action"]      = end_vals[combo_end.currentIndex()]
            s["slideshow_effect"]          = effect_vals[combo_effect.currentIndex()]
            s["slideshow_effect_duration"] = spin_duration.value()
            save_settings(s)

        def _on_start():
            _save()
            dlg.accept()
            self._slideshow_start()

        btn_start.clicked.connect(_on_start)

        dlg.exec()

    def goto_first_page(self):
        """先頭ページへ移動"""
        if self.pages:
            self.current_index = 0
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def goto_last_page(self):
        """最後のページへ移動"""
        if self.pages:
            self.current_index = len(self.pages) - 1
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def _show_goto_page_dialog(self):
        """ページ番号を指定して移動するダイアログ"""
        from PySide6.QtWidgets import QInputDialog
        if not self.pages:
            return
        total = len(self.pages)
        page, ok = QInputDialog.getInt(
            self, tr("goto_title"),
            tr("goto_label", total=total),
            self.current_index + 1, 1, total, 1
        )
        if ok:
            self.current_index = page - 1
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def _toggle_page_list(self):
        """「ページ」ボタン: 左側のページ一覧パネルをトグル表示"""
        if not self.pages:
            return
        self._page_list_visible = not self._page_list_visible
        if self._page_list_visible:
            self._build_page_list()
            # 他のパネルは閉じる
            if self._bookmark_list_visible:
                self._bookmark_list_visible = False
                self.bookmark_list_panel.setVisible(False)
            self._reposition_overlays()
        self.page_list_panel.setVisible(self._page_list_visible)
        if self._page_list_visible:
            self._scroll_page_list_to_current()

    def _toggle_bookmark_list(self):
        """「しおり」ボタン: 左側のしおり一覧パネルをトグル表示"""
        if not self.pages:
            return
        self._bookmark_list_visible = not self._bookmark_list_visible
        if self._bookmark_list_visible:
            self._build_bookmark_list()
            # 他のパネルは閉じる
            if self._page_list_visible:
                self._page_list_visible = False
                self.page_list_panel.setVisible(False)
            self._reposition_overlays()
        self.bookmark_list_panel.setVisible(self._bookmark_list_visible)

    def _build_bookmark_list(self):
        """保存済みのしおり一覧を構築する（ページ番号の昇順）"""
        from PySide6.QtWidgets import QListWidgetItem
        self.bookmark_list_widget.clear()
        total = len(self.pages)
        digits = len(str(total))
        for index in sorted(self._bookmarked_pages.keys()):
            if not (0 <= index < total):
                continue
            label = self._bookmarked_pages[index]
            page_no = f"{index + 1:0{digits}d}"
            text = f"{page_no}   {label}" if label else page_no
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, index)
            self.bookmark_list_widget.addItem(item)

        if self.bookmark_list_widget.count() == 0:
            placeholder = QListWidgetItem(tr("bm_empty"))
            placeholder.setFlags(Qt.NoItemFlags)
            self.bookmark_list_widget.addItem(placeholder)

    def _on_bookmark_list_clicked(self, item):
        """しおり一覧の項目クリックで該当ページへ移動"""
        index = item.data(Qt.UserRole)
        if index is None:
            return
        if 0 <= index < len(self.pages):
            self.current_index = index
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()

    def _build_page_list(self):
        """ページ一覧を構築する（1ページ目が先頭）"""
        from PySide6.QtWidgets import QListWidgetItem
        if self.page_list_widget.count() == len(self.pages):
            return  # 既に構築済み
        self.page_list_widget.clear()
        total = len(self.pages)
        digits = len(str(total))
        for i in range(total):
            name = self._page_names[i] if i < len(self._page_names) else f"{i+1:0{digits}d}"
            item = QListWidgetItem(f"{i + 1:0{digits}d}   {name}")
            self.page_list_widget.addItem(item)

    def _on_page_list_clicked(self, item):
        """ページ一覧の項目クリックで該当ページへ移動"""
        index = self.page_list_widget.row(item)
        if 0 <= index < len(self.pages):
            self.current_index = index
            self.zoom = 1.0
            self._show_page()
            self._update_thumb_highlight()
            self._highlight_page_list_current()

    def _highlight_page_list_current(self):
        """ページ一覧で現在ページを選択状態にする"""
        if 0 <= self.current_index < self.page_list_widget.count():
            self.page_list_widget.setCurrentRow(self.current_index)

    def _scroll_page_list_to_current(self):
        """ページ一覧パネルを現在ページの位置までスクロールする"""
        self._highlight_page_list_current()
        item = self.page_list_widget.item(self.current_index)
        if item:
            from PySide6.QtWidgets import QAbstractItemView
            self.page_list_widget.scrollToItem(item, QAbstractItemView.PositionAtCenter)


    def _toggle_reading_direction(self):
        """サムネイルの読み方向を RTL⇔LTR で切り替え、設定を保存してサムネイルを再構築する"""
        from settings import load_settings, save_settings
        s = load_settings()
        new_dir = "ltr" if s.get("reading_direction", "rtl") == "rtl" else "rtl"
        s["reading_direction"] = new_dir
        save_settings(s)
        self.btn_reading_dir.setText(tr("reading_rtl") if new_dir == "rtl" else tr("reading_ltr"))
        self._build_thumbnail_strip()

    def show_viewer_settings(self):
        """ビューア設定ダイアログ"""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QRadioButton, QPushButton, QButtonGroup
        )
        from settings import load_settings, save_settings

        dlg = QDialog(self)
        dlg.setWindowTitle(tr("vs_title"))
        dlg.setMinimumWidth(360)
        dlg.setStyleSheet("""
            QDialog {
                background: #fdf6ec;
            }
            QLabel {
                color: #3a2000;
                background: transparent;
            }
            QRadioButton {
                color: #3a2000;
                background: transparent;
                font-size: 11pt;
                padding: 4px;
            }
            QPushButton {
                background: #e8d5b5;
                color: #3a2000;
                border: 1px solid rgba(120, 80, 30, 150);
                border-radius: 4px;
                padding: 6px 20px;
                font-size: 10pt;
            }
            QPushButton:hover {
                background: #dcc49a;
            }
        """)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        # --- 1画面に表示するページ数 ---
        label = QLabel(tr("vs_pages_label"))
        label.setStyleSheet("font-weight: bold;")
        layout.addWidget(label)

        radio_row = QHBoxLayout()
        rb1 = QRadioButton(tr("vs_1page"))
        rb2 = QRadioButton(tr("vs_2page"))
        group = QButtonGroup(dlg)
        group.addButton(rb1, 1)
        group.addButton(rb2, 2)
        if self.pages_per_screen == 2:
            rb2.setChecked(True)
        else:
            rb1.setChecked(True)
        radio_row.addWidget(rb1)
        radio_row.addWidget(rb2)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        # --- OK/キャンセル ---
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton(tr("dialog_ok"))
        btn_cancel = QPushButton(tr("dialog_cancel"))
        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        if dlg.exec() == QDialog.Accepted:
            new_value = group.checkedId()
            if new_value in (1, 2) and new_value != self.pages_per_screen:
                self.pages_per_screen = new_value
                # 設定ファイルに保存
                settings = load_settings()
                settings["pages_per_screen"] = new_value
                save_settings(settings)
                # 2ページモードで奇数indexにいる場合の表示も考慮しそのまま再表示
                self.zoom = 1.0
                self._show_page()


    # マウスホイール / キーボード
    # ------------------------------------------------------------------ #

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta < 0:
            self.next_page()
        elif delta > 0:
            self.prev_page()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Right, Qt.Key_D, Qt.Key_Space):
            self.next_page()
        elif key in (Qt.Key_Left, Qt.Key_A):
            self.prev_page()
        elif key in (Qt.Key_Plus, Qt.Key_Equal):
            self.zoom_in()
        elif key in (Qt.Key_Minus, Qt.Key_Underscore):
            self.zoom_out()
        elif key == Qt.Key_F:
            self.cycle_fit_mode()
        elif key == Qt.Key_Escape:
            if self.window().isFullScreen():
                self.toggle_fullscreen()
            elif self.parent() is not None:
                self.back_to_shelf_requested.emit()
            else:
                self.close()
        else:
            super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_overlays()
        self.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._original_pixmap:
            self._apply_display()
        self._reposition_overlays()

    def _reposition_overlays(self):
        """オーバーレイパネルをcentral widget上部・下部に配置する"""
        central = self._central_stack
        w = max(central.width(), self.width())
        h = max(central.height(), self.height())
        top_h = 64
        bottom_h = 4 + 60 + 2 + 160  # margin(4) + ボタン行(60) + spacing(2) + サムネイル行(160)
        self.top_overlay.setGeometry(0, 0, w, top_h)
        self.bottom_overlay.setGeometry(0, h - bottom_h, w, bottom_h)
        self.top_overlay.raise_()
        self.bottom_overlay.raise_()
        # ページリストパネル: 上部・下部オーバーレイの間、左側
        panel_w = 260
        self.page_list_panel.setGeometry(0, top_h, panel_w, h - top_h - bottom_h)
        self.page_list_panel.raise_()
        # しおり一覧パネル: ページリストパネルと同じ位置
        self.bookmark_list_panel.setGeometry(0, top_h, panel_w, h - top_h - bottom_h)
        self.bookmark_list_panel.raise_()

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.RightButton:
                self._toggle_overlay()
                return True
            if event.button() == Qt.LeftButton:
                if self._handle_click_navigation(event.position().x()):
                    return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._toggle_overlay()
        else:
            super().mousePressEvent(event)

    def _handle_click_navigation(self, click_x: float) -> bool:
        """左端クリック→次ページ、右端クリック→前ページ（RTL時）。
        オーバーレイ表示中・ズーム中は無効。クリックゾーン幅は幅の30%か250pxの小さい方。"""
        if self._overlay_visible:
            return False
        if self.zoom != 1.0:
            return False

        vw = self.scroll_area.viewport().width()
        zone = min(int(vw * 0.30), 250)

        from settings import load_settings as _ls
        rtl = _ls().get("reading_direction", "rtl") == "rtl"

        if click_x < zone:
            if rtl:
                self.next_page()
            else:
                self.prev_page()
            return True
        if click_x > vw - zone:
            if rtl:
                self.prev_page()
            else:
                self.next_page()
            return True
        return False

    def _toggle_overlay(self):
        if self._slideshow_running:
            # スライドショー中の右クリック → 停止してメニューを表示
            self._slideshow_stop()
            self._overlay_visible = True
            self._reposition_overlays()
            self.top_overlay.setVisible(True)
            self.bottom_overlay.setVisible(True)
            if self.pages and not self._thumb_widgets:
                from PySide6.QtCore import QTimer as _QTimer
                _QTimer.singleShot(0, self._build_thumbnail_strip)
            return
        self._overlay_visible = not self._overlay_visible
        self._reposition_overlays()
        self.top_overlay.setVisible(self._overlay_visible)
        self.bottom_overlay.setVisible(self._overlay_visible)
        if not self._overlay_visible and self._page_list_visible:
            # メニュー全体を閉じるときはページ一覧も閉じる
            self._page_list_visible = False
            self.page_list_panel.setVisible(False)
        if not self._overlay_visible and self._bookmark_list_visible:
            # メニュー全体を閉じるときはしおり一覧も閉じる
            self._bookmark_list_visible = False
            self.bookmark_list_panel.setVisible(False)
        if self._overlay_visible and self.pages and not self._thumb_widgets:
            # 初回表示時のみサムネイルを構築（再構築は重いので一度だけ）
            from PySide6.QtCore import QTimer as _QTimer
            _QTimer.singleShot(0, self._build_thumbnail_strip)

    # ------------------------------------------------------------------ #
    # 閉じるとき → 進捗保存・スレッド停止
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        self._slideshow_stop()
        self._stop_strip_worker()
        # ワーカーにキャンセルを伝えてシグナルを切断
        if self._page_worker:
            self._page_worker.cancel()
            try:
                self._page_worker.load_done.disconnect()
            except RuntimeError:
                pass
        # スレッドは parent=self で管理されているので
        # isRunning() を呼ばず quit() だけ呼ぶ（既に停止済みでも無害）
        if self._page_thread is not None:
            try:
                self._page_thread.quit()
                self._page_thread.wait(300)
            except RuntimeError:
                pass  # C++オブジェクトが既に削除済み → 無視

        self._page_worker = None
        self._page_thread = None

        if self.pages:
            save_progress(self.file_path, self.current_index)
        super().closeEvent(event)
