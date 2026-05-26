@echo off
REM Build script for creating a single-file Windows EXE with PyInstaller
REM Usage: run this in project root on Windows (double-click or run from PowerShell/CMD)

setlocal
echo Creating virtual environment (.venv_build)...
py -3 -m venv .venv_build
if %ERRORLEVEL% neq 0 (
    echo Failed to create virtualenv. Ensure Python is installed and on PATH.
    pause
    exit /b 1
)

echo Activating virtual environment...
call .venv_build\Scripts\activate.bat

echo Upgrading pip and installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller

echo Running PyInstaller...
REM Include .env next to exe so config.py can read it; adjust icon name if needed
pyinstaller --onefile --name STT_Pro_Bot --icon bot_logo.ico --add-data ".env;." main.py

if %ERRORLEVEL% neq 0 (
    echo PyInstaller failed. Check the log above for errors.
    pause
    exit /b 1
)

echo Build complete. Your executable is in the dist\ directory as STT_Pro_Bot.exe
echo Remember to verify dist\STT_Pro_Bot.exe before running — keep your tokens secret.
pause
