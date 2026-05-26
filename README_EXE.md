# Building a Windows EXE for STT Pro Bot

This document explains how to build a single-file Windows executable (`.exe`) from the Python project using PyInstaller and the provided icon.

Prerequisites
- Windows machine with Python 3.8+ installed and `py` on PATH
- `bot_logo.ico` must exist in project root (this repo already contains it)
- `.env` file with `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY` present in project root (do NOT commit this to GitHub)

Quick build steps (recommended):

1. Open PowerShell in project root (where `main.py` is located).
2. Run the automated script:

```powershell
.\build_exe.bat
```

What the script does
- Creates a small virtual environment `.venv_build`
- Installs `requirements.txt` and `pyinstaller`
- Runs PyInstaller to produce `dist\STT_Pro_Bot.exe` with the `bot_logo.ico` icon
- Bundles the `.env` file next to the exe so `config.py` can read it at runtime

Security notes
- The `.env` file contains secrets (bot token, API keys). Keep `.env` off public repos and share it securely.
- Built exe will include code and potentially secrets if you embed them — avoid embedding tokens inside source.

Troubleshooting
- If imports fail, make sure all packages in `requirements.txt` can be installed on Windows.
- If Gemini/Groq APIs require platform-specific libs, check the PyInstaller log for missing modules and add hooks if needed.

If you want, I can also:
- Create a `.spec` file tailored to include extra data
- Test a local build here (if you want me to run the build on this machine)
