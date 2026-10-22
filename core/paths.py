"""路径工具：区分「可写数据目录」与「只读资源目录」。

开发运行时两者都是项目根；PyInstaller 打包后：
- app_dir()  = exe 所在目录（config.json / logs 等可写数据）
- res_dir()  = sys._MEIPASS（static 等只读资源）
"""
import os
import sys


def app_dir():
    """可写数据目录（打包后 = exe 所在目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def res_dir():
    """只读资源目录（打包后 = 解压资源目录 _MEIPASS）。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
