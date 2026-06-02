@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" "http://localhost:8765"
python -m http.server 8765 2>nul
if errorlevel 1 py -3 -m http.server 8765
