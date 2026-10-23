@echo off
cd /d "%~dp0"

REM resolve python path (python_path.txt has priority)
set "PY="
if exist python_path.txt set /p PY=<python_path.txt
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python not found. Edit python_path.txt with the full path to python.exe.
  pause
  exit /b 1
)

REM create an isolated build venv on first run (avoid bundling the whole Anaconda env)
if not exist .venv-build (
  echo Creating build venv ...
  "%PY%" -m venv .venv-build
  if errorlevel 1 ( echo venv create failed & pause & exit /b 1 )
  ".venv-build\Scripts\python.exe" -m pip install fastapi uvicorn pystray pillow pyinstaller
  if errorlevel 1 ( echo pip install failed & pause & exit /b 1 )
)

set "BUILD_PY=.venv-build\Scripts\python.exe"

REM locate required DLLs (ffi/libssl/libcrypto) from the python installation
for %%I in ("%PY%") do set "PYDIR=%%~dpI"
set "DLLDIR=%PYDIR%Library\bin"
if not exist "%DLLDIR%\ffi.dll" set "DLLDIR=%PYDIR%"

echo Building ...
"%BUILD_PY%" -m PyInstaller --noconfirm --onedir --windowed --name rtt-manager ^
  --add-data "static;static" ^
  --add-data "config.default.json;." ^
  --add-binary "%DLLDIR%\ffi.dll;." ^
  --add-binary "%DLLDIR%\ffi-8.dll;." ^
  --add-binary "%DLLDIR%\libcrypto-3-x64.dll;." ^
  --add-binary "%DLLDIR%\libssl-3-x64.dll;." ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.loops.asyncio ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.http.h11_impl ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import uvicorn.protocols.websockets.websockets_impl ^
  --hidden-import uvicorn.lifespan.on ^
  tray.py

if errorlevel 1 ( echo Build failed & pause & exit /b 1 )

echo.
echo Done: dist\rtt-manager\rtt-manager.exe
echo Copy the whole dist\rtt-manager folder as the portable edition.
pause
