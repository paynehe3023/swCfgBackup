# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 — 交换机配置备份工具（命令行版）
用法：
  python build.py

生成 dist/交换机配置备份工具.exe
"""

import subprocess
import sys
import os
import shutil

# 打包前校验 paramiko 版本：5.x 不再兼容只支持 ssh-rsa 的老式交换机
try:
    import paramiko
    _PARAMIKO_VERSION = paramiko.__version__
except ImportError:
    _PARAMIKO_VERSION = ""

if not _PARAMIKO_VERSION.startswith("3."):
    print(f"[错误] 打包环境 paramiko={_PARAMIKO_VERSION or '未安装'}，"
          f"必须使用 3.x（先执行 pip install -r requirements.txt）")
    sys.exit(1)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

APP_NAME = "交换机配置备份工具"
ENTRY_SCRIPT = "backup_tool.py"

HIDDEN_IMPORTS = [
    "backup",
    "collector",
    "inventory",
    "utils",
    "version",
    "paramiko",
    "openpyxl",
    "cryptography",
    "cffi",
    "bcrypt",
    "nacl",
]

EXCLUDE_MODULES = [
    # --- 标准库中不需要的 ---
    "tkinter.test", "tkinter.__main__",
    "unittest", "pydoc", "doctest", "pdb", "test",
    "xmlrpc", "lib2to3",
    "turtle", "turtledemo",
    "tkinter.dialog", "tkinter.colorchooser", "tkinter.filedialog",
    "tkinter.font", "tkinter.messagebox", "tkinter.simpledialog",
    "tkinter.scrolledtext", "tkinter.tix", "tkinter.constants",
    # --- 包管理器（运行时不需要）---
    "pip", "ensurepip", "setuptools",
    "wheel", "pkg_resources",
    # --- 第三方包：paramiko 不需要这些 ---
    "invoke",               # fabric 的依赖，paramiko 不需要
    "fabric",               # 不使用 fabric
    # --- openpyxl 可选依赖 ---
    "numpy", "PIL", "lxml", "matplotlib", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
]


def build():
    print("=" * 50)
    print("  交换机配置备份工具 — PyInstaller 打包")
    print("=" * 50)

    # 清理（容错处理）
    for d in ["build_cli"]:
        p = os.path.join(BASE_DIR, d)
        if os.path.isdir(p):
            try:
                shutil.rmtree(p)
            except Exception:
                pass
    spec_file = os.path.join(BASE_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec_file):
        try:
            os.remove(spec_file)
        except Exception:
            pass

    dist_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    upx_path = os.path.join(BASE_DIR, "upx.exe")
    use_upx = os.path.isfile(upx_path)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", APP_NAME,
        "--noconfirm",
        "--clean",
        "--distpath", dist_dir,
        "--workpath", os.path.join(BASE_DIR, "build_cli"),
    ]

    if use_upx:
        cmd += ["--upx-dir", BASE_DIR]
        print("  [优化] 启用 UPX 压缩")

    for mod in EXCLUDE_MODULES:
        cmd += ["--exclude-module", mod]

    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]

    cmd += ["--collect-submodules", "paramiko"]
    version_file = os.path.join(BASE_DIR, "version_info.txt")
    if os.path.isfile(version_file):
        cmd += ["--version-file", version_file]
    cmd += [os.path.join(BASE_DIR, ENTRY_SCRIPT)]

    print(f"  工作目录: {BASE_DIR}")
    print(f"  排除模块: {len(EXCLUDE_MODULES)} 个")
    print(f"  隐藏导入: {len(HIDDEN_IMPORTS)} 个\n")

    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print(f"\n  [错误] 打包失败 (exit code: {result.returncode})")
        sys.exit(1)

    exe_path = os.path.join(dist_dir, f"{APP_NAME}.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  [成功] 打包完成!")
        print(f"  输出文件: {exe_path}")
        print(f"  文件大小: {size_mb:.1f} MB")

        build_dir = os.path.join(BASE_DIR, "build_cli")
        if os.path.isdir(build_dir):
            try:
                shutil.rmtree(build_dir)
            except Exception:
                pass
        if os.path.isfile(spec_file):
            try:
                os.remove(spec_file)
            except Exception:
                pass
        print(f"  [清理] 已删除中间构建文件")
    else:
        print(f"\n  [错误] 未找到输出文件: {exe_path}")
        sys.exit(1)

    print(f"\n{'=' * 50}")


if __name__ == "__main__":
    build()
