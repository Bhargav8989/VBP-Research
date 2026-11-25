@echo off
cd /d "%~dp0"
echo Starting VBP Invest Event Analyzer at http://127.0.0.1:8000 ...
start "" http://127.0.0.1:8000
".venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8000 --reload
