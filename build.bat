@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt -q
python build.py
if errorlevel 1 exit /b 1
echo.
echo Откройте out\index.html в браузере (F11 — полный экран)
