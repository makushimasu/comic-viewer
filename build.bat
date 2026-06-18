@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  Comic Viewer Build Script
echo ========================================
echo.

rem -------------------------------------------------------
rem コード署名の設定（証明書取得後にコメントを外して設定）
rem -------------------------------------------------------
rem set "SIGN_PFX=C:\path\to\your_certificate.pfx"
rem set "SIGN_PASS=your_pfx_password"
rem set "SIGN_TIMESTAMP=http://timestamp.sectigo.com"
rem
rem 署名コマンド（signtool は Windows SDK に含まれる）:
rem signtool sign /f "%SIGN_PFX%" /p "%SIGN_PASS%" /tr "%SIGN_TIMESTAMP%" /td sha256 /fd sha256 /v "%~1"
rem -------------------------------------------------------

if not exist venv\Scripts\activate.bat (
    echo [ERROR] venv not found. Run start.bat first.
    pause
    exit /b 1
)

set "PYI=venv\Scripts\pyinstaller.exe"

if not exist "%PYI%" (
    echo [1/4] Installing PyInstaller...
    venv\Scripts\python.exe -m pip install pyinstaller --quiet
    if errorlevel 1 (
        echo [ERROR] pip install failed.
        pause
        exit /b 1
    )
) else (
    echo [1/4] PyInstaller already installed.
)

echo [2/4] Building Comic Viewer app...
"%PYI%" comic_viewer_win.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller app failed.
    pause
    exit /b 1
)
echo       Done: dist\ComicViewer\

rem --- 署名（SIGN_PFX が設定されている場合のみ実行） ---
if defined SIGN_PFX (
    echo       Signing ComicViewer.exe...
    signtool sign /f "%SIGN_PFX%" /p "%SIGN_PASS%" /tr "%SIGN_TIMESTAMP%" /td sha256 /fd sha256 /v "dist\ComicViewer\ComicViewer.exe"
)

echo [3/4] Building uninstaller...
if exist dist\uninstall.exe (
    del /f /q dist\uninstall.exe
    timeout /t 2 /nobreak >nul
)
"%PYI%" uninstaller.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller uninstaller failed.
    pause
    exit /b 1
)
echo       Done: dist\uninstall.exe

rem --- 署名 ---
if defined SIGN_PFX (
    echo       Signing uninstall.exe...
    signtool sign /f "%SIGN_PFX%" /p "%SIGN_PASS%" /tr "%SIGN_TIMESTAMP%" /td sha256 /fd sha256 /v "dist\uninstall.exe"
)

echo [4/4] Building installer (bundles app + uninstaller)...
"%PYI%" installer.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller installer failed.
    pause
    exit /b 1
)
echo       Done: dist\ComicViewerSetup.exe

rem --- 署名 ---
if defined SIGN_PFX (
    echo       Signing ComicViewerSetup.exe...
    signtool sign /f "%SIGN_PFX%" /p "%SIGN_PASS%" /tr "%SIGN_TIMESTAMP%" /td sha256 /fd sha256 /v "dist\ComicViewerSetup.exe"
)

echo.
echo ========================================
echo  Build complete!
echo  Installer: dist\ComicViewerSetup.exe
echo ========================================
echo.
pause
