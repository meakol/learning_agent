@echo off
cd /d "%~dp0"
if not defined PORT set PORT=8124
echo Lecture Notes Agent
echo Starting http://127.0.0.1:%PORT% ...
python -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%
pause
