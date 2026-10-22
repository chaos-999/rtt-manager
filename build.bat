@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 读取 Python 路径（优先 python_path.txt）
set "PY="
if exist python_path.txt set /p PY=<python_path.txt
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python not found. Edit python_path.txt.
  pause
  exit /b 1
)

REM 首次打包时创建独立构建环境，避免把 Anaconda 全家桶打进去
if not exist .venv-build (
  echo Creating build venv ...
  "%PY%" -m venv .venv-build
  if errorlevel 1 ( echo venv create failed & pause & exit /b 1 )
  ".venv-build\Scripts\python.exe" -m pip install fastapi uvicorn pystray pillow pyinstaller
  if errorlevel 1 ( echo pip install failed & pause & exit /b 1 )
)

set "BUILD_PY=.venv-build\Scripts\python.exe"

REM 从当前 Python 安装目录定位打包所需的 DLL（ffi/libssl/libcrypto）
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
echo 整个 dist\rtt-manager 文件夹即为免安装绿色版，可直接复制到任意机器运行。
pause
