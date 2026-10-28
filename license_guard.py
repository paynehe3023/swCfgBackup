# -*- coding: utf-8 -*-
"""离线注册码校验（商业版）。

安全模型：
  - 注册码由 Ed25519 私钥签发，程序只内置公钥，无法自行生成有效注册码；
  - 注册码绑定本机机器码，复制到其他电脑无效；
  - 注册码保存在 %APPDATA%\\swCfgBackup\\license.dat，升级新版本继续有效；
  - 私钥仅保存在供应商本地（license_tools/private_key.pem），不要提交或分发。

注意：这是客户端离线校验，能防止普通复制和随意生成注册码；
如果源码公开，开发者仍可通过修改源码绕过，商业分发建议只发布 exe。
"""
import base64
import hashlib
import json
import os
import sys
import uuid
import zlib
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from version import APP_NAME, APP_VERSION

PRODUCT = "swCfgBackup"
LICENSE_PREFIX = "SWCFG1"
LICENSE_VERSION = 1

# Ed25519 公钥（对应 license_tools/private_key.pem）
PUBLIC_KEY_B64 = "BOYwQYpozu8CnAowXubtLfk283HTFDG5WspyC3LxIQY="


class LicenseError(Exception):
    """注册码无效"""


def _appdata_dir() -> Path:
    base = os.getenv("APPDATA") or os.getenv("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "swCfgBackup"


LICENSE_PATH = _appdata_dir() / "license.dat"


# ------------------------------------------------------------------ #
#  机器码                                                             #
# ------------------------------------------------------------------ #
def _machine_guid() -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Cryptography") as key:
            value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(value).strip()
    except Exception:
        return ""


def _volume_serial(drive: str = "C:\\") -> str:
    if os.name != "nt":
        return ""
    try:
        import ctypes
        from ctypes import wintypes
        serial = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive), None, 0,
            ctypes.byref(serial), None, None, None, 0)
        return f"{serial.value:08X}" if ok else ""
    except Exception:
        return ""


def _raw_fingerprint() -> str:
    guid = _machine_guid()
    if guid:
        # MachineGuid 在同一次 Windows 安装中稳定，重装系统后会变化
        return f"win|{guid}"
    return "|".join([
        "fallback",
        str(uuid.getnode()),
        os.environ.get("COMPUTERNAME", ""),
        _volume_serial(),
    ])


def machine_code() -> str:
    """本机机器码（26 位 Base32，按 5 位分组）"""
    digest = hashlib.sha256(_raw_fingerprint().encode("utf-8")).digest()[:16]
    text = base64.b32encode(digest).decode("ascii").rstrip("=")
    return "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def normalize_machine_code(code: str) -> str:
    return "".join(ch for ch in str(code or "").upper() if ch.isalnum())


# ------------------------------------------------------------------ #
#  注册码编解码 / 校验                                                #
# ------------------------------------------------------------------ #
def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_license(code: str, check_machine: bool = True) -> Dict:
    """校验注册码，返回载荷；失败抛 LicenseError。"""
    code = "".join(str(code or "").split())
    if not code:
        raise LicenseError("注册码为空")
    if len(code) > 20000:
        raise LicenseError("注册码长度异常")
    parts = code.split(".")
    if len(parts) != 3 or parts[0].upper() != LICENSE_PREFIX:
        raise LicenseError("注册码格式不正确")

    try:
        payload_z = _b64d(parts[1])
        signature = _b64d(parts[2])
    except Exception:
        raise LicenseError("注册码编码不正确")

    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(PUBLIC_KEY_B64))
        public.verify(signature, payload_z)
    except Exception:
        raise LicenseError("注册码签名无效")

    try:
        decompressor = zlib.decompressobj()
        raw = decompressor.decompress(payload_z, 65536)
        if decompressor.unconsumed_tail:
            raise ValueError("payload too large")
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        raise LicenseError("注册码内容损坏")

    if data.get("p") != PRODUCT:
        raise LicenseError("注册码不属于本产品")
    try:
        if int(data.get("v", 0)) != LICENSE_VERSION:
            raise LicenseError("注册码版本不兼容")
    except (TypeError, ValueError):
        raise LicenseError("注册码版本信息损坏")

    if check_machine:
        if (normalize_machine_code(data.get("m"))
                != normalize_machine_code(machine_code())):
            raise LicenseError("注册码不适用于本机（机器码不一致）")

    expires = str(data.get("x") or "").strip()
    if expires:
        try:
            expire_date = datetime.strptime(expires, "%Y-%m-%d").date()
        except ValueError:
            raise LicenseError("注册码有效期格式错误")
        if date.today() > expire_date:
            raise LicenseError(f"注册码已过期（{expires}）")

    return data


def load_license_code() -> str:
    try:
        return LICENSE_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def save_license_code(code: str) -> None:
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = LICENSE_PATH.with_suffix(".tmp")
    tmp.write_text(str(code).strip(), encoding="utf-8")
    os.replace(tmp, LICENSE_PATH)


def check_saved_license() -> Tuple[bool, str]:
    """检查已保存的注册码，返回 (是否有效, 失败原因)"""
    code = load_license_code()
    if not code:
        return False, "尚未激活"
    try:
        verify_license(code)
        return True, ""
    except LicenseError as exc:
        return False, str(exc)
    except Exception as exc:
        return False, f"读取注册码失败：{exc}"


# ------------------------------------------------------------------ #
#  激活窗口                                                           #
# ------------------------------------------------------------------ #
def run_activation() -> bool:
    """商业版启动前调用；已有有效注册码则直接返回 True。"""
    ok, reason = check_saved_license()
    if ok:
        return True

    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    BG = "#1e2330"
    SIDEBAR = "#161b27"
    CARD = "#252b3b"
    TEXT = "#e2e8f0"
    TEXT2 = "#94a3b8"
    ACCENT = "#3b82f6"
    OK = "#22c55e"
    ERR = "#ef4444"
    BORDER = "#334155"
    FONT = ("Microsoft YaHei UI", 9)
    FONT_SMALL = ("Microsoft YaHei UI", 8)
    FONT_HEAD = ("Microsoft YaHei UI", 10, "bold")
    FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")

    root = tk.Tk()
    root.title(f"{APP_NAME} - 软件激活")
    root.configure(bg=BG)
    root.geometry("720x600")
    root.resizable(False, False)

    try:
        base = getattr(sys, "_MEIPASS",
                       os.path.dirname(os.path.abspath(__file__)))
        ico = os.path.join(base, "image", "icon.ico")
        if os.path.isfile(ico):
            root.iconbitmap(ico)
        png = os.path.join(base, "image", "icon.png")
        if os.path.isfile(png):
            photo = tk.PhotoImage(file=png)
            factor = max(1, photo.width() // 64)
            photo = photo.subsample(factor, factor)
            root._icon = photo
            root.iconphoto(True, photo)
    except Exception:
        pass

    header = tk.Frame(root, bg=SIDEBAR)
    header.pack(fill=tk.X)
    tk.Label(header, text=f"🛡  {APP_NAME}", font=FONT_TITLE,
             bg=SIDEBAR, fg=TEXT).pack(side=tk.LEFT, padx=20, pady=14)
    tk.Label(header, text=f"v{APP_VERSION}", font=FONT,
             bg=SIDEBAR, fg=TEXT2).pack(side=tk.RIGHT, padx=20)

    body = tk.Frame(root, bg=BG)
    body.pack(fill=tk.BOTH, expand=True, padx=20, pady=14)

    if reason and reason != "尚未激活":
        tk.Label(body, text=f"当前注册码无效：{reason}", font=FONT,
                 bg=BG, fg=ERR, anchor="w", justify="left",
                 wraplength=660).pack(fill=tk.X, pady=(0, 8))

    tk.Label(body, text="第一步：把本机机器码发给供应商", font=FONT_HEAD,
             bg=BG, fg=TEXT, anchor="w").pack(fill=tk.X, pady=(4, 4))
    mc = machine_code()
    mc_var = tk.StringVar(value=mc)
    mc_row = tk.Frame(body, bg=BG)
    mc_row.pack(fill=tk.X, pady=(0, 10))
    mc_entry = tk.Entry(mc_row, textvariable=mc_var, font=("Consolas", 12),
                        bg=CARD, fg=TEXT, insertbackground=TEXT,
                        relief=tk.FLAT, bd=0, highlightthickness=1,
                        highlightcolor=ACCENT, highlightbackground=BORDER,
                        state="readonly", readonlybackground=CARD)
    mc_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

    def copy_machine_code():
        try:
            root.clipboard_clear()
            root.clipboard_append(mc)
            status_label.config(text="机器码已复制到剪贴板",
                                fg=OK)
        except Exception as exc:
            status_label.config(text=f"复制失败：{exc}", fg=ERR)

    tk.Button(mc_row, text="复制", font=FONT, bg=ACCENT, fg="white",
              relief=tk.FLAT, bd=0, padx=12, pady=4, cursor="hand2",
              command=copy_machine_code).pack(side=tk.LEFT, padx=(8, 0))

    tk.Label(body, text="获取激活码请联系 payne，微信：947919822",
             font=("Microsoft YaHei UI", 10, "bold"), bg=BG, fg=OK,
             anchor="w").pack(fill=tk.X, pady=(0, 10))

    tk.Label(body, text="第二步：粘贴供应商提供的注册码", font=FONT_HEAD,
             bg=BG, fg=TEXT, anchor="w").pack(fill=tk.X, pady=(4, 4))
    code_text = scrolledtext.ScrolledText(
        body, height=7, bg=CARD, fg=TEXT, font=("Consolas", 9),
        insertbackground=TEXT, relief=tk.FLAT, bd=0, wrap=tk.WORD,
        highlightthickness=1, highlightcolor=ACCENT,
        highlightbackground=BORDER)
    code_text.pack(fill=tk.X)

    status_label = tk.Label(body, text="注册码只对本机有效；升级新版本不需要重新激活。",
                            font=FONT_SMALL, bg=BG, fg=TEXT2,
                            anchor="w", justify="left", wraplength=660)
    status_label.pack(fill=tk.X, pady=(8, 8))

    activated = {"ok": False}

    def do_activate():
        code = code_text.get("1.0", "end").strip()
        if not code:
            status_label.config(text="请粘贴注册码", fg=ERR)
            return
        try:
            info = verify_license(code)
        except LicenseError as exc:
            status_label.config(text=f"激活失败：{exc}", fg=ERR)
            return
        try:
            save_license_code(code)
        except Exception as exc:
            status_label.config(text=f"注册码有效，但保存失败：{exc}", fg=ERR)
            return
        activated["ok"] = True
        messagebox.showinfo(
            "激活成功",
            f"软件已激活。\n\n客户：{info.get('c') or '-'}\n"
            f"到期：{info.get('x') or '永久'}",
            parent=root)
        root.destroy()

    def do_close():
        root.destroy()

    btn_row = tk.Frame(body, bg=BG)
    btn_row.pack(fill=tk.X, pady=(0, 4))
    tk.Button(btn_row, text="  ✓  激活  ", font=FONT_HEAD,
              bg=OK, fg="white", relief=tk.FLAT, bd=0,
              padx=14, pady=7, cursor="hand2",
              command=do_activate).pack(side=tk.LEFT)
    tk.Button(btn_row, text="退出", font=FONT,
              bg=CARD, fg=TEXT, relief=tk.FLAT, bd=0,
              padx=14, pady=7, cursor="hand2",
              command=do_close).pack(side=tk.LEFT, padx=8)

    code_text.focus_set()
    root.protocol("WM_DELETE_WINDOW", do_close)
    root.update_idletasks()
    width, height = 720, 600
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.mainloop()
    return activated["ok"]
