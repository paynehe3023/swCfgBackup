# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 — 交换机配置备份工具 GUI 版
用法：
  python build_gui.py

生成 dist/交换机配置备份工具GUI.exe
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

# 项目根目录（build_gui.py 所在目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 打包配置
APP_NAME = "交换机配置备份工具GUI"
ENTRY_SCRIPT = "backup_gui.py"

# 需要打包的 Python 模块
HIDDEN_IMPORTS = [
    "backup",
    "collector",
    "inventory",
    "utils",
    "version",
    "paramiko",
    "openpyxl",
]

# paramiko 依赖的加密库
HIDDEN_IMPORTS += [
    "cryptography",
    "cffi",
    "bcrypt",
    "nacl",       # PyNaCl 的 import 名
]

# 排除的不必要模块（减小体积）
# ⚠️ tkinter 整个包必须完整保留，不要排除任何 tkinter.* 子模块
#    之前排除 tkinter.test/__main__/tix 等导致整个 tkinter 没被打包，启动报
#    "No module named 'tkinter.constants'"
EXCLUDE_MODULES = [
    # --- 标准库中不需要的 ---
    "unittest", "pydoc", "doctest", "pdb", "test",
    "xmlrpc", "lib2to3",
    "turtle", "turtledemo",
    # --- 包管理器（运行时不需要）---
    "pip", "ensurepip", "setuptools",
    "wheel", "pkg_resources",
    # --- 第三方包：paramiko 不需要这些 ---
    "invoke",               # fabric 的依赖，paramiko 不需要
    "fabric",               # 不使用 fabric
    # --- openpyxl 可选依赖（运行时用不到）---
    "numpy", "PIL", "PIL.Image", "lxml", "lxml.etree",
    # --- 不需要的数据/绘图库 ---
    "matplotlib", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
]


def build():
    print("=" * 50)
    print("  交换机配置备份工具 GUI — PyInstaller 打包")
    print("=" * 50)

    # 清理旧的构建产物
    for d in ["build_gui"]:
        p = os.path.join(BASE_DIR, d)
        if os.path.isdir(p):
            try:
                shutil.rmtree(p)
            except Exception:
                pass  # 沙箱保护可能导致删除失败，忽略
    spec_file = os.path.join(BASE_DIR, f"{APP_NAME}.spec")
    if os.path.isfile(spec_file):
        try:
            os.remove(spec_file)
        except Exception:
            pass

    # 确保输出目录
    dist_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    # 构建 UPX 参数
    upx_path = os.path.join(BASE_DIR, "upx.exe")
    use_upx = os.path.isfile(upx_path)

    # 构建命令
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",                           # 单文件 exe
        "--windowed",                          # GUI 程序（不弹出控制台窗口）
        "--name", APP_NAME,
        "--noconfirm",                         # 不询问确认
        "--clean",                             # 清理缓存
        "--distpath", dist_dir,                # 输出到 dist/
        "--workpath", os.path.join(BASE_DIR, "build_gui"),
    ]

    # 图标与 image 资源（缺失时降级为默认图标，不中断打包）
    icon_path = os.path.join(BASE_DIR, "image", "icon.ico")
    if os.path.isfile(icon_path):
        cmd += ["--icon", icon_path]
    else:
        print("  [提示] 未找到 image/icon.ico，使用默认图标")
    image_dir = os.path.join(BASE_DIR, "image")
    if os.path.isdir(image_dir):
        cmd += ["--add-data", f"{image_dir};image"]
    version_file = os.path.join(BASE_DIR, "version_info.txt")
    if os.path.isfile(version_file):
        cmd += ["--version-file", version_file]

    # UPX 压缩
    if use_upx:
        cmd += ["--upx-dir", BASE_DIR]
        print("  [优化] 启用 UPX 压缩")
    else:
        print("  [提示] 未找到 upx.exe，跳过 UPX 压缩")

    # 排除不必要的模块
    for mod in EXCLUDE_MODULES:
        cmd += ["--exclude-module", mod]

    # 添加隐藏导入
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]

    # tkinter 子模块：PyInstaller 静态分析对 `from tkinter import xxx` 有时会漏，
    # 手动声明确保整个 tkinter 包齐全
    cmd += ["--collect-submodules", "tkinter"]
    cmd += ["--collect-submodules", "_tkinter"]

    # 收集 paramiko 子模块（cryptography 不需要 collect-submodules，PyInstaller 会自动发现需要的）
    cmd += ["--collect-submodules", "paramiko"]

    # 工作目录设为项目根
    cmd += [os.path.join(BASE_DIR, ENTRY_SCRIPT)]

    print(f"\n  工作目录: {BASE_DIR}")
    print(f"  排除模块: {len(EXCLUDE_MODULES)} 个")
    print(f"  隐藏导入: {len(HIDDEN_IMPORTS)} 个")
    print()

    result = subprocess.run(cmd, cwd=BASE_DIR)

    if result.returncode != 0:
        print(f"\n  [错误] 打包失败 (exit code: {result.returncode})")
        sys.exit(1)

    # 验证输出
    exe_path = os.path.join(dist_dir, f"{APP_NAME}.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print(f"\n  [成功] 打包完成!")
        print(f"  输出文件: {exe_path}")
        print(f"  文件大小: {size_mb:.1f} MB")

        # 清理中间文件
        build_dir = os.path.join(BASE_DIR, "build_gui")
        if os.path.isdir(build_dir):
            shutil.rmtree(build_dir)
        if os.path.isfile(spec_file):
            os.remove(spec_file)
        print(f"  [清理] 已删除中间构建文件")
    else:
        print(f"\n  [错误] 未找到输出文件: {exe_path}")
        sys.exit(1)

    print(f"\n{'=' * 50}")


if __name__ == "__main__":
    build()
