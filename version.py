# -*- coding: utf-8 -*-
"""应用版本与仓库信息（界面、关于窗口、更新检查、构建共用）"""

APP_NAME = "网络设备配置备份"
APP_VERSION = "0.0.2"
APP_AUTHOR = "payne"

GITHUB_OWNER = "paynehe3023"
GITHUB_REPO = "swCfgBackup"
GITHUB_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
GITHUB_RELEASES_URL = f"{GITHUB_URL}/releases"
GITHUB_RELEASES_ATOM = f"{GITHUB_URL}/releases.atom"
GITHUB_LATEST_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)


def version_tuple(value: str) -> tuple:
    """把 v1.2.3 这类版本号转成可比较的整数元组"""
    text = str(value or "").strip().lstrip("vV")
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def is_newer_version(latest: str, current: str) -> bool:
    """latest 是否比 current 新"""
    a, b = version_tuple(latest), version_tuple(current)
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))
