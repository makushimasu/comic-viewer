@echo off
setlocal enabledelayedexpansion
title Comic Viewer Setup

set "INSTALL_DIR=%LOCALAPPDATA%\Programs\Comic Viewer"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs"

echo.
echo  ============================================
echo    Comic Viewer  Setup
echo  ============================================
echo.
echo  Install location:
echo    %INSTALL_DIR%
echo.
choice /M "Proceed with installation?" /C YN
if errorlevel 2 (echo Cancelled. & exit /b 0)

if exist "%INSTALL_DIR%" (
    echo Removing previous installation...
    rmdir /s /q "%INSTALL_DIR%"
)

echo Copying files...
xcopy /E /I /Q "%~dp0ComicViewer" "%INSTALL_DIR%"
if errorlevel 1 (
    echo [ERROR] Copy failed.
    pause
    exit /b 1
)

echo Creating Start Menu shortcuts...
powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut('%STARTMENU%\Comic Viewer.lnk');$s.TargetPath='%INSTALL_DIR%\ComicViewer.exe';$s.WorkingDirectory='%INSTALL_DIR%';$s.Save()"

echo Creating uninstaller...
(
    echo @echo off
    echo cd /d %%TEMP%%
    echo rmdir /s /q "%INSTALL_DIR%"
    echo del "%STARTMENU%\Comic Viewer.lnk" 2^>nul
    echo del "%STARTMENU%\Uninstall Comic Viewer.lnk" 2^>nul
    echo del "%USERPROFILE%\Desktop\Comic Viewer.lnk" 2^>nul
    echo echo Uninstall complete.
    echo pause
) > "%INSTALL_DIR%\uninstall.bat"

powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut('%STARTMENU%\Uninstall Comic Viewer.lnk');$s.TargetPath='%INSTALL_DIR%\uninstall.bat';$s.WorkingDirectory='%INSTALL_DIR%';$s.Save()"

echo.
choice /M "Create Desktop shortcut?" /C YN
if not errorlevel 2 (
    powershell -NoProfile -Command "$ws=New-Object -ComObject WScript.Shell;$s=$ws.CreateShortcut('%USERPROFILE%\Desktop\Comic Viewer.lnk');$s.TargetPath='%INSTALL_DIR%\ComicViewer.exe';$s.WorkingDirectory='%INSTALL_DIR%';$s.Save()"
    echo Desktop shortcut created.
)

echo.
echo  ============================================
echo    Setup complete!
echo    Start Menu > Comic Viewer
echo  ============================================
echo.
choice /M "Launch Comic Viewer now?" /C YN
if not errorlevel 2 start "" "%INSTALL_DIR%\ComicViewer.exe"
endlocal
