# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本 — GUI 免费版 / 注册版

用法：
    python build_gui.py                  # 同时构建免费版和注册版（默认）
    python build_gui.py --edition free
    python build_gui.py --edition commercial

输出：
    dist/交换机配置备份工具GUI.exe          # 免费版（仅本地使用，不上传 GitHub）
    dist/交换机配置备份工具GUI-注册版.exe    # 注册版（GitHub 只发布这个）
    dist/swCfgBackup-v<版本>-win64.exe      # 注册版的 ASCII 发布附件
"""
import argparse
import os
import shutil
import subprocess
import sys

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
sys.path.insert(0, BASE_DIR)
try:
    from version import APP_VERSION
except Exception:
    APP_VERSION = "0.0.0"

EDITIONS = {
    "free": {
        "name": "swCfgBackup",
        "entry": "backup_gui.py",
        "work": "build_gui_free",
        "commercial": False,
        "generator": False,
        "version_file": "version_info.txt",
    },
    "commercial": {
        "name": "swCfgBackupS",
        "entry": "backup_gui_commercial.py",
        "work": "build_gui_commercial",
        "commercial": True,
        "generator": False,
        "version_file": "version_info_commercial.txt",
    },
    "generator": {
        "name": "swCfgBackupS-注册机",
        "entry": "license_tools/generator_gui.py",
        "work": "build_generator",
        "commercial": False,
        "generator": True,
        "version_file": "version_info_tool.txt",
    },
}

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
    "unittest", "pydoc", "doctest", "pdb", "test",
    "xmlrpc", "lib2to3",
    "turtle", "turtledemo",
    "pip", "ensurepip", "setuptools",
    "wheel", "pkg_resources",
    "invoke", "fabric",
    "numpy", "PIL", "PIL.Image", "lxml", "lxml.etree",
    "matplotlib", "pandas", "scipy",
    "PyQt5", "PyQt6", "PySide2", "PySide6",
]


def _clean(path: str) -> None:
    if os.path.isdir(path):
        try:
            shutil.rmtree(path)
        except Exception:
            pass
    elif os.path.isfile(path):
        try:
            os.remove(path)
        except Exception:
            pass


def build_one(edition: str) -> str:
    cfg = EDITIONS[edition]
    name = cfg["name"]
    entry = cfg["entry"]
    work_dir = os.path.join(BASE_DIR, cfg["work"])
    dist_dir = os.path.join(BASE_DIR, "dist")
    os.makedirs(dist_dir, exist_ok=True)

    print("=" * 60)
    print(f"  {'注册版' if cfg['commercial'] else '免费版'} — PyInstaller 打包")
    print("=" * 60)

    _clean(work_dir)
    spec_file = os.path.join(BASE_DIR, f"{name}.spec")
    _clean(spec_file)

    use_upx = os.path.isfile(os.path.join(BASE_DIR, "upx.exe"))

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        "--name", name,
        "--noconfirm",
        "--clean",
        "--distpath", dist_dir,
        "--workpath", work_dir,
    ]

    icon_path = os.path.join(BASE_DIR, "image", "icon.ico")
    if os.path.isfile(icon_path):
        cmd += ["--icon", icon_path]
    else:
        print("  [提示] 未找到 image/icon.ico，使用默认图标")

    image_dir = os.path.join(BASE_DIR, "image")
    if os.path.isdir(image_dir):
        cmd += ["--add-data", f"{image_dir};image"]

    version_file = os.path.join(BASE_DIR, cfg["version_file"])
    if os.path.isfile(version_file):
        cmd += ["--version-file", version_file]

    if use_upx:
        cmd += ["--upx-dir", BASE_DIR]
        print("  [优化] 启用 UPX 压缩")

    for mod in EXCLUDE_MODULES:
        cmd += ["--exclude-module", mod]

    hidden = list(HIDDEN_IMPORTS)
    if cfg["commercial"]:
        hidden += ["license_guard", "backup_gui"]
    if cfg["generator"]:
        hidden = ["license_guard", "make_license", "reset_local_license",
                  "version", "cryptography", "tkcalendar", "babel",
                  "babel.numbers", "babel.dates"]
    for mod in hidden:
        cmd += ["--hidden-import", mod]

    cmd += ["--collect-submodules", "tkinter"]
    cmd += ["--collect-submodules", "_tkinter"]
    if cfg["generator"]:
        cmd += ["--collect-submodules", "tkcalendar"]
        cmd += ["--collect-data", "babel"]
    if not cfg["generator"]:
        cmd += ["--collect-submodules", "paramiko"]
    cmd += [os.path.join(BASE_DIR, entry)]

    print(f"  入口: {entry}")
    print(f"  输出: {os.path.join(dist_dir, name + '.exe')}")
    print()

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"\n  [错误] {edition} 打包失败 (exit code: {result.returncode})")
        sys.exit(1)

    exe_path = os.path.join(dist_dir, f"{name}.exe")
    if not os.path.exists(exe_path):
        print(f"\n  [错误] 未找到输出文件: {exe_path}")
        sys.exit(1)

    size_mb = os.path.getsize(exe_path) / (1024 * 1024)
    print(f"\n  [成功] {exe_path}  ({size_mb:.1f} MB)")

    _clean(work_dir)
    _clean(spec_file)
    print("  [清理] 已删除中间构建文件\n")
    return exe_path


def main() -> None:
    parser = argparse.ArgumentParser(description="构建免费版 / 注册版 / 注册机")
    parser.add_argument("--edition",
                        choices=["free", "commercial", "generator", "all"],
                        default="all", help="默认构建全部三个 exe")
    args = parser.parse_args()

    editions = (["free", "commercial", "generator"]
                if args.edition == "all" else [args.edition])
    built = {}
    for edition in editions:
        built[edition] = build_one(edition)

    print("=" * 60)
    print(f"  免费版（本地使用，不要上传）：{built.get('free', '未构建')}")
    print(f"  注册版（GitHub 只上传这个）：{built.get('commercial', '未构建')}")
    print(f"  注册机（仅作者本地使用）：{built.get('generator', '未构建')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
