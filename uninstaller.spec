# uninstaller.spec  — Comic Viewer アンインストーラー (単一 exe)
# uac_admin=True で起動時に自動でUAC昇格を要求する。

block_cipher = None

a = Analysis(
    ['uninstaller.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['tkinter', 'tkinter.messagebox'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6'],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='uninstall',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,       # UPX圧縮無効（有効にするとAVの誤検知が増える）
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon='icon.ico',
)
