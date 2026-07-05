# help_docs.py — 本棚モード / ビューアモードのヘルプ（説明書）
# show_help_dialog(parent, "shelf" | "viewer") で表示する。

from i18n import tr

_CSS = """
    h2 { color: #5a3a10; border-bottom: 2px solid #c9a86a; padding-bottom: 4px; }
    h3 { color: #6a4a1a; margin-top: 18px; margin-bottom: 6px; }
    p, li { color: #2a2a2a; font-size: 10.5pt; line-height: 1.5; }
    table { border-collapse: collapse; margin: 6px 0; }
    th { background: #ead9b8; color: #3a2000; padding: 4px 10px; border: 1px solid #c9a86a; }
    td { padding: 4px 10px; border: 1px solid #d9c49a; color: #2a2a2a; }
    code { background: #f0e6d2; color: #5a3a10; padding: 1px 5px; border-radius: 3px; }
"""

HELP_SHELF = {
"ja": """
<h2>本棚モードの使い方</h2>

<h3>本の登録</h3>
<ul>
<li>ツールバー左端の<b>「追加（＋）」</b>ボタン、またはメニューの「ファイル」から<b>フォルダ／ファイルを追加</b>できます（追加ボタンは本棚トップでのみ表示されます）。</li>
<li>エクスプローラーからフォルダやファイルを本棚に<b>ドラッグ＆ドロップ</b>しても登録できます（複数可）。</li>
</ul>

<h3>対応フォーマット</h3>
<table>
<tr><th>種類</th><th>拡張子</th></tr>
<tr><td>ZIPアーカイブ</td><td>.zip .cbz</td></tr>
<tr><td>RARアーカイブ</td><td>.rar .cbr（Windowsでは 7-Zip のインストール推奨）</td></tr>
<tr><td>7zアーカイブ</td><td>.7z .cb7</td></tr>
<tr><td>PDF</td><td>.pdf（アーカイブ内のPDFも対応）</td></tr>
<tr><td>画像</td><td>.jpg .jpeg .png .webp .gif .bmp</td></tr>
</table>

<h3>本棚の操作</h3>
<ul>
<li><b>ダブルクリック</b>／<b>Enter（Return）キー</b>: フォルダは中に入り、本（アーカイブ・PDF・画像）はビューアで開きます（キーボードの矢印キーで項目を選んで Enter でも開けます）。</li>
<li><b>ホーム</b>: 本棚トップ（登録一覧）へ戻ります。</li>
<li><b>上へ</b>: 1階層上のフォルダへ戻ります。</li>
<li><b>更新</b>: 現在のフォルダを再スキャンします。</li>
<li><b>履歴</b>: 最近読んだ本（30件）から選んで開けます。</li>
<li><b>表示</b>: サムネイルの大きさをプリセット間でワンクリック切替できます。</li>
<li><b>検索ボックス</b>: サブフォルダまで再帰的にファイル名検索します。</li>
<li><b>パンくずリスト</b>（本棚の左下）: 現在のフォルダ階層と、選択中のファイル名を表示します。
クリックでその階層へジャンプできます（設定の「フォルダとファイル名を表示」で非表示にもできます）。</li>
</ul>

<h3>しおりバッジ</h3>
<ul>
<li><b>赤いしおり</b>: 読みかけの本（前回のページから再開できます）</li>
<li><b>青いしおり</b>: 読み終わった本</li>
</ul>

<h3>並び順・フィルタ・シリーズ</h3>
<ul>
<li><b>並び順</b>: 名前順／追加日順（フォルダ内は更新日順）／最終閲覧順／手動を切り替えられます。</li>
<li><b>手動配置</b>: 並び順で「手動」を選ぶと、本やフォルダを<b>ドラッグして好きな段へ自由に配置</b>できます。
何もない空いた場所にも置けて、配置は次回起動時も維持されます。元に戻したいときは並び順メニューの
<b>「この本棚の手動配置をリセット（名前順に戻す）」</b>を選んでください（リセットは開いている本棚だけに
効き、他の本棚の配置はそのまま残ります）。</li>
<li><b>シリーズをまとめる</b>（並び順メニュー内）: 「〇〇 第1巻」「〇〇 第2巻」のような
同名巻数違いを1つにまとめて「〇〇（全N冊）」と表示します。ダブルクリックで中の巻一覧を開き、
「上へ」で戻ります。</li>
<li><b>フィルタ</b>: すべて／未読のみ／読みかけのみ／読了のみで絞り込めます。</li>
<li><b>統計</b>: 登録数・読了数・しおり数・最近開いた冊数などを確認できます。</li>
</ul>

<h3>設定でできること</h3>
<ul>
<li>サムネイルの大きさ・スクロールバー表示・フォルダとファイル名（パンくず）表示</li>
<li>ページキャッシュの容量上限・キャッシュ削除</li>
<li>ビューアの起動方法（本棚に埋め込み／別ウィンドウ）</li>
<li>言語（日本語／English）</li>
</ul>
""",
"en": """
<h2>Bookshelf Mode</h2>

<h3>Adding Books</h3>
<ul>
<li>Use the <b>Add (+)</b> button at the left end of the toolbar, or the File menu, to
<b>add folders / files</b> (the Add button appears only at the shelf top).</li>
<li>You can also <b>drag &amp; drop</b> folders or files from Explorer onto the shelf.</li>
</ul>

<h3>Supported Formats</h3>
<table>
<tr><th>Type</th><th>Extensions</th></tr>
<tr><td>ZIP archive</td><td>.zip .cbz</td></tr>
<tr><td>RAR archive</td><td>.rar .cbr (7-Zip recommended on Windows)</td></tr>
<tr><td>7z archive</td><td>.7z .cb7</td></tr>
<tr><td>PDF</td><td>.pdf (PDFs inside archives also supported)</td></tr>
<tr><td>Images</td><td>.jpg .jpeg .png .webp .gif .bmp</td></tr>
</table>

<h3>Navigation</h3>
<ul>
<li><b>Double-click</b> or <b>Enter (Return) key</b>: enter a folder, or open a book in the viewer
(you can also select an item with the arrow keys and press Enter).</li>
<li><b>Home</b>: back to the shelf top (registered items).</li>
<li><b>Up</b>: go up one folder level.</li>
<li><b>Refresh</b>: rescan the current folder.</li>
<li><b>History</b>: reopen one of the last 30 books.</li>
<li><b>View</b>: cycle thumbnail size between presets with one click.</li>
<li><b>Search box</b>: recursive filename search including subfolders.</li>
<li><b>Breadcrumb</b> (bottom-left of the shelf): shows the current folder path and the
selected file name; click a segment to jump there (can be hidden in Settings).</li>
</ul>

<h3>Bookmark Badges</h3>
<ul>
<li><b>Red bookmark</b>: in progress (resumes from the last page)</li>
<li><b>Blue bookmark</b>: finished</li>
</ul>

<h3>Sort, Filter &amp; Series</h3>
<ul>
<li><b>Sort</b>: by name / by date added (modified date inside folders) / by last read / manual.</li>
<li><b>Manual arrangement</b>: choose "Manual" in the Sort menu, then <b>drag books or folders
onto any shelf row</b> — including empty ones. Positions persist across restarts.</li>
<li><b>Group series</b> (in the Sort menu): volumes like "Title vol.1" and "Title vol.2"
are grouped into a single "Title (N vols)" item. Double-click to browse the volumes,
and use <b>Up</b> to go back.</li>
<li><b>Filter</b>: show all / unread only / in progress only / finished only.</li>
<li><b>Stats</b>: registered count, finished count, bookmarks, recently opened books.</li>
</ul>

<h3>Settings</h3>
<ul>
<li>Thumbnail size, scrollbar, folder &amp; file name (breadcrumb) display</li>
<li>Page cache size limit and cache clearing</li>
<li>Viewer mode (embedded / separate window)</li>
<li>Language (日本語 / English)</li>
</ul>
""",
}

HELP_VIEWER = {
"ja": """
<h2>ビューアモードの使い方</h2>

<h3>基本操作</h3>
<table>
<tr><th>操作</th><th>動作</th></tr>
<tr><td>マウスホイール</td><td>ページ送り（縦読みモード中はスクロール）</td></tr>
<tr><td>画面の左右クリック</td><td>ページ送り／戻し（読み方向に連動）</td></tr>
<tr><td><b>右クリック</b></td><td>メニューの表示／非表示</td></tr>
<tr><td><code>Esc</code></td><td>全画面解除 → 本棚へ戻る</td></tr>
</table>

<h3>マウスジェスチャー（右ボタンを押したままドラッグ）</h3>
<table>
<tr><th>ジェスチャー</th><th>動作</th></tr>
<tr><td>← 左へドラッグ</td><td>次のページ</td></tr>
<tr><td>→ 右へドラッグ</td><td>前のページ</td></tr>
<tr><td>↑ 上へドラッグ</td><td>全画面切替</td></tr>
<tr><td>↓ 下へドラッグ</td><td>本棚へ戻る</td></tr>
</table>
<p>動かさずに右クリックを離すと従来通りメニューが開きます。</p>

<h3>キーボード（デフォルト。設定で変更可）</h3>
<table>
<tr><th>キー</th><th>動作</th></tr>
<tr><td><code>→</code> <code>D</code> <code>Space</code></td><td>次のページ</td></tr>
<tr><td><code>←</code> <code>A</code></td><td>前のページ</td></tr>
<tr><td><code>+</code> / <code>-</code></td><td>ズームイン／アウト</td></tr>
<tr><td><code>F</code></td><td>フィットモード切替（全体→横幅→縦幅）</td></tr>
<tr><td><code>F11</code></td><td>全画面切替</td></tr>
<tr><td><code>L</code></td><td>ルーペ（カーソル周辺を原寸表示）</td></tr>
<tr><td><code>V</code></td><td>縦読みモード切替</td></tr>
</table>

<h3>上部メニュー（右クリックで表示）</h3>
<ul>
<li><b>フォルダ</b>: この本があるフォルダを開く　<b>本棚</b>: 本棚へ戻る　<b>フルスクリーン</b>: 全画面表示</li>
<li><b>ヘルプガイド</b>: この説明書を表示　<b>設定</b>: 見開き・自動分割・余白カット・明るさ・グレースケール・背景色・<b>キー割り当てのカスタマイズ</b></li>
</ul>

<h3>下部メニュー（右クリックで表示）</h3>
<ul>
<li><b>移動</b>: 次の本／前の本／先頭／最後／ページ指定ジャンプ</li>
<li><b>ページ</b>: ページ一覧パネル　<b>しおり</b>: しおり一覧パネル</li>
<li><b>スライドショー</b>: 自動ページ送り（間隔・エフェクト設定可）</li>
<li><b>フィット</b>: 表示モード切替　<b>綴じ方向</b>: 右綴じ⇔左綴じ　<b>縦読み</b>: 縦スクロール表示</li>
<li>下部の<b>サムネイル一覧</b>: クリックでページ移動、<b>右クリック</b>でしおり追加・ページ回転</li>
</ul>

<h3>便利な機能</h3>
<ul>
<li><b>横長ページの自動分割</b>: 見開きスキャンを自動で1ページずつ表示（見開き2ページモードでは単独全幅表示）。</li>
<li><b>進捗の自動保存</b>: 本を閉じても次回同じページから再開されます。</li>
<li><b>ページキャッシュ</b>: 一度開いた本は2回目から高速に開きます。</li>
</ul>
""",
"en": """
<h2>Viewer Mode</h2>

<h3>Basics</h3>
<table>
<tr><th>Action</th><th>Result</th></tr>
<tr><td>Mouse wheel</td><td>Turn pages (scrolls in vertical mode)</td></tr>
<tr><td>Click left / right side</td><td>Turn pages (follows reading direction)</td></tr>
<tr><td><b>Right-click</b></td><td>Show / hide menus</td></tr>
<tr><td><code>Esc</code></td><td>Exit fullscreen → back to shelf</td></tr>
</table>

<h3>Mouse Gestures (drag while holding the right button)</h3>
<table>
<tr><th>Gesture</th><th>Action</th></tr>
<tr><td>← Drag left</td><td>Next page</td></tr>
<tr><td>→ Drag right</td><td>Previous page</td></tr>
<tr><td>↑ Drag up</td><td>Toggle fullscreen</td></tr>
<tr><td>↓ Drag down</td><td>Back to shelf</td></tr>
</table>
<p>Releasing without moving opens the menus as usual.</p>

<h3>Keyboard (defaults; customizable in Settings)</h3>
<table>
<tr><th>Key</th><th>Action</th></tr>
<tr><td><code>→</code> <code>D</code> <code>Space</code></td><td>Next page</td></tr>
<tr><td><code>←</code> <code>A</code></td><td>Previous page</td></tr>
<tr><td><code>+</code> / <code>-</code></td><td>Zoom in / out</td></tr>
<tr><td><code>F</code></td><td>Cycle fit mode (window → width → height)</td></tr>
<tr><td><code>F11</code></td><td>Toggle fullscreen</td></tr>
<tr><td><code>L</code></td><td>Loupe (magnify around the cursor)</td></tr>
<tr><td><code>V</code></td><td>Toggle vertical scroll mode</td></tr>
</table>

<h3>Top Menu (right-click to show)</h3>
<ul>
<li><b>Folder</b>: open the containing folder&nbsp;&nbsp;<b>Shelf</b>: back to the bookshelf&nbsp;&nbsp;<b>Fullscreen</b></li>
<li><b>Help Guide</b>: show this manual&nbsp;&nbsp;<b>Settings</b>: spread mode, auto-split, margin crop, brightness, grayscale, background color, <b>key binding customization</b></li>
</ul>

<h3>Bottom Menu (right-click to show)</h3>
<ul>
<li><b>Move</b>: next / previous book, first / last page, go to page</li>
<li><b>Pages</b>: page list panel&nbsp;&nbsp;<b>Bookmarks</b>: bookmark list panel</li>
<li><b>Slideshow</b>: automatic page turning (interval / effects)</li>
<li><b>Fit</b>: display mode&nbsp;&nbsp;<b>Binding</b>: RTL ⇔ LTR&nbsp;&nbsp;<b>Vertical</b>: webtoon-style scroll</li>
<li><b>Thumbnail strip</b>: click to jump, <b>right-click</b> for bookmarks / rotation</li>
</ul>

<h3>More Features</h3>
<ul>
<li><b>Auto-split wide pages</b>: spread scans are shown one page at a time (shown alone full-width in 2-page mode).</li>
<li><b>Auto-saved progress</b>: reopening a book resumes from the last page.</li>
<li><b>Page cache</b>: books open much faster from the second time.</li>
</ul>
""",
}


def _current_lang() -> str:
    try:
        from settings import load_settings
        lang = load_settings().get("language", "ja")
        return lang if lang in ("ja", "en") else "ja"
    except Exception:
        return "ja"


def show_help_dialog(parent, mode: str):
    """ヘルプダイアログを表示する。mode: "shelf" | "viewer" """
    from PySide6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTextBrowser
    )

    lang = _current_lang()
    if mode == "viewer":
        title = tr("help_viewer_title")
        body = HELP_VIEWER.get(lang, HELP_VIEWER["ja"])
    else:
        title = tr("help_shelf_title")
        body = HELP_SHELF.get(lang, HELP_SHELF["ja"])

    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.resize(720, 640)
    dlg.setStyleSheet("QDialog { background: #faf5ee; }")

    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(12, 12, 12, 12)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    browser.setStyleSheet("""
        QTextBrowser {
            background: #fdf9f2;
            border: 1px solid #c9a86a;
            border-radius: 6px;
            padding: 12px;
        }
    """)
    browser.document().setDefaultStyleSheet(_CSS)
    browser.setHtml(body)
    layout.addWidget(browser)

    btn_row = QHBoxLayout()
    btn_row.addStretch()
    btn_close = QPushButton(tr("help_close"))
    btn_close.setStyleSheet("""
        QPushButton {
            background: #5a8a3c; color: white;
            border-radius: 6px; padding: 8px 24px; font-weight: bold;
        }
        QPushButton:hover { background: #4a7a2c; }
    """)
    btn_close.clicked.connect(dlg.accept)
    btn_row.addWidget(btn_close)
    layout.addLayout(btn_row)

    dlg.exec()
