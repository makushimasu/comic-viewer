@echo off
cd /d "%~dp0"

if not exist venv\Scripts\activate.bat (
    echo [Setup] Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [Setup] Installing packages...
    python -m pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

python main.py
pause
