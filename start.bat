@echo off
cd /d "%~dp0"

set "PY="

REM read python path from python_path.txt (configurable)
if exist python_path.txt (
  set /p PY=<python_path.txt
)

REM fallback: python in PATH
if not defined PY where python >nul 2>nul && set "PY=python"

if not defined PY (
  echo [ERROR] Python not found.
  echo Edit "python_path.txt" in this folder and put the full path to python.exe on the first line.
  echo Example: D:\anaconda3\python.exe
  pause
  exit /b 1
)

REM derive pythonw.exe path (same dir as python.exe) to run without console window
set "PYW=%PY:python.exe=pythonw.exe%"
if not exist "%PYW%" set "PYW=%PY%"

echo Starting rtt-manager in background (system tray) ...
start "" "%PYW%" "%~dp0tray.py"
