# comic_viewer.spec  — PyInstaller ビルド設定
# 使い方: pyinstaller comic_viewer.spec --clean --noconfirm
#         または build.bat を実行

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[('icon.png', '.')],
    hiddenimports=[
        # ローカルモジュール（import chainで拾われない場合の保険）
        'archive', 'core', 'viewer', 'settings', 'i18n', 'utils',
        'page_cache', 'wood_bg', 'appdir',
        # PySide6: 動的ロードされるモジュール
        'PySide6.QtSvg',
        'PySide6.QtXml',
        'PySide6.QtPrintSupport',
        # PDF対応（pdfium DLLはhooks-contribが自動収集する）
        'pypdfium2', 'pypdfium2_raw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 明らかに不要なPySide6モジュールを除外してサイズを削減
    excludes=[
        'tkinter',
        'PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',     'PySide6.Qt3DLogic', 'PySide6.Qt3DRender',
        'PySide6.QtBluetooth',   'PySide6.QtCharts',  'PySide6.QtDataVisualization',
        'PySide6.QtMultimedia',  'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc',         'PySide6.QtPositioning',
        'PySide6.QtQml',         'PySide6.QtQuick',   'PySide6.QtQuickControls2',
        'PySide6.QtQuickWidgets','PySide6.QtRemoteObjects',
        'PySide6.QtSensors',     'PySide6.QtSerialBus','PySide6.QtSerialPort',
        'PySide6.QtSpatialAudio','PySide6.QtSql',     'PySide6.QtStateMachine',
        'PySide6.QtTest',        'PySide6.QtTextToSpeech',
        'PySide6.QtWebChannel',  'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineQuick','PySide6.QtWebEngineWidgets',
        'PySide6.QtWebSockets',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ComicViewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX圧縮無効（有効にするとAVの誤検知が増える）
    console=False,          # コンソールウィンドウを非表示
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ComicViewer',
)
