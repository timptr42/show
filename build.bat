@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Сборка презентации

echo.
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo.
    echo [ERR] Не удалось установить зависимости.
    pause
    exit /b 1
)

python build.py
set EXITCODE=%ERRORLEVEL%
exit /b %EXITCODE%
