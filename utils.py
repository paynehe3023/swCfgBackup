# -*- coding: utf-8 -*-
"""
公共工具模块
提取各模块重复使用的代码，统一维护。

包含：
  - fix_console_encoding(): Windows 控制台 UTF-8 修复
  - check_dependencies(): 运行时依赖检查
"""

import sys
import os


def get_app_dir():
    """
    获取应用程序所在目录。

    - PyInstaller --onefile 模式：sys.executable 指向 exe 文件，
      __file__ 指向临时解压目录（如 %TEMP%\\_MEIxxxxx），应使用 sys.executable
    - PyInstaller --onedir 模式：sys.executable 指向 dist\\app.exe，
      依赖在 _internal/ 子目录，也应使用 sys.executable
    - 普通 Python 脚本：使用 __file__ 所在目录

    Returns:
        应用程序根目录的绝对路径字符串
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # 普通 Python 脚本运行
        return os.path.dirname(os.path.abspath(__file__))


def fix_console_encoding():
    """
    Windows 控制台 UTF-8 输出修复。

    使用 reconfigure() 原地修改，避免替换 sys.stdout 对象导致底层
    buffer 被 GC 关闭，从而引发多线程下 ValueError: I/O op on closed file。
    """
    if sys.platform == "win32":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def check_dependencies(packages=None, gui=False):
    """
    检查运行时依赖是否已安装。

    Args:
        packages: 要检查的包名列表，默认 ["paramiko", "openpyxl"]
        gui: 是否使用 tkinter GUI 弹窗提示（用于 backup_gui.py）

    Returns:
        True 如果全部已安装，否则退出程序（exit(1)）
    """
    if packages is None:
        packages = ["paramiko", "openpyxl"]

    missing = []
    for pkg in packages:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if not missing:
        return True

    install_cmd = f"pip install {' '.join(missing)}"

    if gui:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "缺少依赖",
                f"请先在命令行执行：\n{install_cmd}"
            )
        except Exception:
            print(f"[错误] 缺少依赖库，请先运行：{install_cmd}")
    else:
        print(f"[错误] 缺少依赖库，请先运行：{install_cmd}")

    sys.exit(1)
