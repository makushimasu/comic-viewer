# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for comic_viewer

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[
        'PIL._imaging',
        'PIL.Image',
        'PIL.ImageFilter',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtXml',
        'PySide6.QtSvg',
        # ローカルモジュール（import chainで拾われない場合の保険）
        'archive', 'core', 'viewer', 'settings', 'i18n', 'utils',
        'page_cache', 'wood_bg', 'appdir', 'help_docs',
        # PDF対応
        'pypdfium2', 'pypdfium2_raw',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'numpy', 'scipy',
        # 未使用の Qt モジュールを除外してサイズ削減
        'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtQmlModels',
        'PySide6.QtQmlMeta', 'PySide6.QtQmlWorkerScript',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtLocation', 'PySide6.QtPositioning',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtWebEngine', 'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets', 'PySide6.QtWebChannel',
        'PySide6.QtBluetooth', 'PySide6.QtNfc',
        'PySide6.QtSensors', 'PySide6.QtSerialPort',
        'PySide6.Qt3DCore', 'PySide6.Qt3DRender',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization',
        'PySide6.QtVirtualKeyboard',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 使わない Qt .so を除去してサイズ削減
_EXCLUDE_LIBS = {
    'libQt6Quick', 'libQt6Qml', 'libQt6QmlModels', 'libQt6QmlMeta',
    'libQt6QmlWorkerScript', 'libQt6Pdf', 'libQt6PdfWidgets',
    'libQt6Location', 'libQt6Positioning', 'libQt6PositioningQuick',
    'libQt6Multimedia', 'libQt6MultimediaWidgets', 'libQt6MultimediaQuick',
    'libQt6WebEngineCore', 'libQt6WebEngineWidgets', 'libQt6WebChannel',
    'libQt6Bluetooth', 'libQt6Nfc', 'libQt6Sensors',
    'libQt6VirtualKeyboard', 'libQt6Charts', 'libQt6DataVisualization',
    'libQt63DCore', 'libQt63DRender',
}

def _keep(name):
    base = name.split('/')[-1].split('.')[0]
    return base not in _EXCLUDE_LIBS

a.binaries = [(n, p, t) for n, p, t in a.binaries if _keep(n)]
a.datas    = [(n, p, t) for n, p, t in a.datas    if _keep(n)]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='comic_viewer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=True,
    upx=True,
    upx_exclude=[],
    name='comic_viewer',
)

# ビルド後にスクリプト・アイコンをコピー
import shutil, os
_dist = os.path.join(DISTPATH, 'comic_viewer')
for _f in ['install.sh', 'uninstall.sh', 'icon.png']:
    shutil.copy(os.path.join(SPECPATH, _f), os.path.join(_dist, _f))
os.chmod(os.path.join(_dist, 'install.sh'),   0o755)
os.chmod(os.path.join(_dist, 'uninstall.sh'), 0o755)
