@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ========================================
echo  Comic Viewer Build Script
echo ========================================
echo.

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

echo [4/4] Building installer (bundles app + uninstaller)...
"%PYI%" installer.spec --clean --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller installer failed.
    pause
    exit /b 1
)
echo       Done: dist\ComicViewerSetup.exe

echo.
echo ========================================
echo  Build complete!
echo  Installer: dist\ComicViewerSetup.exe
echo ========================================
echo.
pause
