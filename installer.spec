# installer.spec  — PyInstaller: GUI インストーラーを単一 exe にパック
#
# ビルド手順:
#   1. pyinstaller comic_viewer.spec --clean --noconfirm   (dist/ComicViewer/ を生成)
#   2. pyinstaller installer.spec   --clean --noconfirm   (dist/ComicViewerSetup.exe を生成)
#
# dist/ComicViewer/ を丸ごとバンドルするため、先に 1 を実行すること。

block_cipher = None

a = Analysis(
    ['installer.py'],
    pathex=['.'],
    binaries=[],
    # dist/ComicViewer と dist/uninstall.exe をインストーラー内に埋め込む
    datas=[
        ('dist/ComicViewer', 'ComicViewer'),
        ('dist/uninstall.exe', '.'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # PySide6 は installer.py では使わない
        'PySide6',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

# --onefile 相当: binaries/datas を EXE に直接埋め込む
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,   # ← COLLECT に渡さず EXE に直接
    a.datas,      # ← 同上 (dist/ComicViewer も含まれる)
    [],
    name='ComicViewerSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # コンソールウィンドウを出さない
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,  # 起動時に UAC 昇格を要求するマニフェストを埋め込む
    icon='icon.ico',
)
