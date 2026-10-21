"""托盘常驻启动脚本。

用 pythonw.exe 运行本文件，不出现控制台窗口，仅显示系统托盘图标。
托盘菜单：打开控制台 / 退出。
"""
import os
import threading
import webbrowser
import logging
from logging.handlers import RotatingFileHandler

import pystray
from PIL import Image, ImageDraw

import uvicorn
from main import app

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"

# 日志写入文件，便于后台模式下排查
handler = RotatingFileHandler(
    os.path.join(LOG_DIR, "app.log"), maxBytes=1024 * 1024, backupCount=3, encoding="utf-8"
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])


def _make_icon():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=12, fill=(47, 111, 237, 255))
    d.ellipse([20, 20, 44, 44], fill=(255, 255, 255, 255))
    return img


_server = None
_server_thread = None


def _start_server():
    """启动 uvicorn 服务线程（用可控的 Server 对象，便于重启）。"""
    global _server, _server_thread
    config = uvicorn.Config(app, host=HOST, port=PORT, log_config=None, log_level="info")
    _server = uvicorn.Server(config)
    _server_thread = threading.Thread(target=_server.run, daemon=True)
    _server_thread.start()


def _on_open(icon, item):
    webbrowser.open(URL)


def _on_restart(icon, item):
    """重启后端服务：优雅停止当前服务，再重新启动。"""
    global _server, _server_thread
    if _server is not None:
        _server.should_exit = True
        if _server_thread is not None:
            _server_thread.join(timeout=5)
    _start_server()


def _on_quit(icon, item):
    if _server is not None:
        _server.should_exit = True
    icon.stop()


def main():
    _start_server()

    menu = pystray.Menu(
        pystray.MenuItem("打开控制台", _on_open, default=True),
        pystray.MenuItem("重启服务", _on_restart),
        pystray.MenuItem("退出", _on_quit),
    )
    icon = pystray.Icon("rtt-manager", _make_icon(), "蜘蛛网络控制台", menu)
    icon.run()


if __name__ == "__main__":
    main()
