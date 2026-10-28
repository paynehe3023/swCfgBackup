# -*- coding: utf-8 -*-
"""swCfgBackupS 注册机（仅作者本地使用，请勿外传）。

- 读取本地 private_key.pem 签发注册码；
- 私钥不会打包进本程序，需与程序放在同一目录，或放在项目的 license_tools 下；
- 不要上传本 exe，也不要发给客户。
"""
import os
import sys
import textwrap
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from version import APP_VERSION  # noqa: E402
import make_license  # noqa: E402


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()


def default_key_path() -> Path:
    candidates = [
        APP_DIR / "private_key.pem",
        APP_DIR / "license_tools" / "private_key.pem",
        APP_DIR.parent / "license_tools" / "private_key.pem",
        Path(__file__).resolve().parent / "private_key.pem",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[2]


def default_ledger_path() -> Path:
    if getattr(sys, "frozen", False):
        return APP_DIR / "issued.csv"
    return Path(__file__).resolve().parent / "issued.csv"


BG = "#1e2330"
SIDEBAR = "#161b27"
CARD = "#252b3b"
TEXT = "#e2e8f0"
TEXT2 = "#94a3b8"
ACCENT = "#3b82f6"
OK = "#22c55e"
ERR = "#ef4444"
WARN = "#f59e0b"
BORDER = "#334155"
FONT = ("Microsoft YaHei UI", 9)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_HEAD = ("Microsoft YaHei UI", 10, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
FONT_MONO = ("Consolas", 9)


class GeneratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"swCfgBackupS 注册机  v{APP_VERSION}")
        self.configure(bg=BG)
        self.geometry("820x700")
        self.minsize(760, 620)

        try:
            base = Path(getattr(sys, "_MEIPASS", BASE))
            ico = base / "image" / "icon.ico"
            png = base / "image" / "icon.png"
            if ico.is_file():
                self.iconbitmap(str(ico))
            if png.is_file():
                photo = tk.PhotoImage(file=str(png))
                factor = max(1, photo.width() // 64)
                self._icon = photo.subsample(factor, factor)
                self.iconphoto(True, self._icon)
        except Exception:
            pass

        self._last_code = ""
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=SIDEBAR)
        header.pack(fill=tk.X)
        tk.Label(header, text="swCfgBackupS 注册机", font=FONT_TITLE,
                 bg=SIDEBAR, fg=TEXT).pack(side=tk.LEFT, padx=20, pady=14)
        tk.Label(header, text=f"v{APP_VERSION}  ·  仅作者本地使用，请勿外传",
                 font=FONT_SMALL, bg=SIDEBAR, fg=WARN).pack(side=tk.RIGHT, padx=20)

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=18, pady=12)
        body.columnconfigure(1, weight=1)

        def add_row(row, label, widget):
            tk.Label(body, text=label, font=FONT, bg=BG, fg=TEXT2
                     ).grid(row=row, column=0, sticky="e", padx=(0, 10), pady=5)
            widget.grid(row=row, column=1, sticky="ew", pady=5)

        def make_entry(var,**kw):
            return tk.Entry(body, textvariable=var, font=FONT, bg=CARD,
                            fg=TEXT, insertbackground=TEXT, relief=tk.FLAT,
                            bd=0, highlightthickness=1,
                            highlightcolor=ACCENT,
                            highlightbackground=BORDER, **kw)

        self._v_machine = tk.StringVar()
        add_row(0, "机器码", make_entry(self._v_machine))
        self._v_customer = tk.StringVar()
        add_row(1, "客户名称", make_entry(self._v_customer))
        self._v_expires = tk.StringVar()
        add_row(2, "到期日（可选）", make_entry(self._v_expires))
        tk.Label(body, text="格式 YYYY-MM-DD，留空表示永久",
                 font=FONT_SMALL, bg=BG, fg=TEXT2
                 ).grid(row=3, column=1, sticky="w", pady=(0, 4))

        key_row = tk.Frame(body, bg=BG)
        key_row.grid(row=4, column=1, sticky="ew", pady=5)
        key_row.columnconfigure(0, weight=1)
        self._v_key = tk.StringVar(value=str(default_key_path()))
        key_entry = tk.Entry(key_row, textvariable=self._v_key, font=FONT_SMALL,
                             bg=CARD, fg=TEXT, insertbackground=TEXT,
                             relief=tk.FLAT, bd=0, highlightthickness=1,
                             highlightcolor=ACCENT,
                             highlightbackground=BORDER)
        key_entry.grid(row=0, column=0, sticky="ew")
        tk.Button(key_row, text="浏览", font=FONT_SMALL, bg=CARD, fg=TEXT,
                  relief=tk.FLAT, bd=0, padx=10, pady=3, cursor="hand2",
                  command=self._browse_key).grid(row=0, column=1, padx=(6, 0))
        tk.Label(body, text="私钥文件（private_key.pem）", font=FONT,
                 bg=BG, fg=TEXT2).grid(row=4, column=0, sticky="e", padx=(0, 10))

        self._v_force = tk.BooleanVar(value=False)
        tk.Checkbutton(body, text="允许同一机器码重发（--force）",
                       variable=self._v_force, font=FONT_SMALL,
                       bg=BG, fg=TEXT2, selectcolor=CARD,
                       activebackground=BG, activeforeground=TEXT
                       ).grid(row=5, column=1, sticky="w", pady=(2, 8))

        btn_row = tk.Frame(body, bg=BG)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="w", pady=(0, 8))
        tk.Button(btn_row, text="  ✓  生成注册码  ", font=FONT_HEAD,
                  bg=OK, fg="white", relief=tk.FLAT, bd=0,
                  padx=14, pady=7, cursor="hand2",
                  command=self._generate).pack(side=tk.LEFT)
        tk.Button(btn_row, text="清空", font=FONT, bg=CARD, fg=TEXT,
                  relief=tk.FLAT, bd=0, padx=14, pady=7, cursor="hand2",
                  command=self._clear).pack(side=tk.LEFT, padx=8)

        self._status = tk.Label(body, text="填写用户机器码后生成注册码。",
                                font=FONT_SMALL, bg=BG, fg=TEXT2,
                                anchor="w", justify="left", wraplength=760)
        self._status.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(0, 8))

        self._result = scrolledtext.ScrolledText(
            body, height=11, bg=CARD, fg=TEXT, font=FONT_MONO,
            insertbackground=TEXT, relief=tk.FLAT, bd=0, wrap=tk.WORD,
            highlightthickness=1, highlightcolor=ACCENT,
            highlightbackground=BORDER)
        self._result.grid(row=8, column=0, columnspan=2, sticky="nsew")
        body.rowconfigure(8, weight=1)

        result_btns = tk.Frame(body, bg=BG)
        result_btns.grid(row=9, column=0, columnspan=2, sticky="w", pady=(8, 0))
        tk.Button(result_btns, text="复制注册码", font=FONT, bg=ACCENT,
                  fg="white", relief=tk.FLAT, bd=0, padx=12, pady=5,
                  cursor="hand2", command=self._copy).pack(side=tk.LEFT)
        tk.Button(result_btns, text="保存到文件", font=FONT, bg=CARD,
                  fg=TEXT, relief=tk.FLAT, bd=0, padx=12, pady=5,
                  cursor="hand2", command=self._save).pack(side=tk.LEFT, padx=8)

    def _browse_key(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择私钥文件",
            filetypes=[("PEM 私钥", "*.pem"), ("所有文件", "*.*")])
        if path:
            self._v_key.set(path)

    def _generate(self):
        machine = self._v_machine.get().strip()
        customer = self._v_customer.get().strip()
        expires = self._v_expires.get().strip()
        key_path = self._v_key.get().strip()
        if not machine:
            self._status.config(text="请填写机器码", fg=ERR)
            return
        try:
            result = make_license.generate_license(
                machine,
                customer=customer,
                expires=expires,
                private_key_path=Path(key_path) if key_path else None,
                ledger_path=default_ledger_path(),
                force=self._v_force.get(),
            )
        except make_license.IssueError as exc:
            self._status.config(text=f"生成失败：{exc}", fg=ERR)
            return
        except Exception as exc:
            self._status.config(text=f"生成失败：{type(exc).__name__}: {exc}",
                                fg=ERR)
            return

        self._last_code = result["code"]
        payload = result["payload"]
        text = (
            f"机器码 : {result['machine']}\n"
            f"客户   : {payload['c'] or '-'}\n"
            f"签发日 : {payload['i']}\n"
            f"到期日 : {result['expires'] or '永久'}\n"
            f"授权ID : {result['license_id']}\n"
            + "-" * 70 + "\n"
            + textwrap.fill(result["code"], 76)
        )
        self._result.delete("1.0", tk.END)
        self._result.insert("1.0", text)
        self._status.config(text="生成成功，已自动复制注册码到剪贴板。", fg=OK)
        try:
            self.clipboard_clear()
            self.clipboard_append(result["code"])
        except Exception:
            pass

    def _copy(self):
        if not self._last_code:
            self._status.config(text="还没有生成注册码", fg=WARN)
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(self._last_code)
            self._status.config(text="注册码已复制到剪贴板", fg=OK)
        except Exception as exc:
            self._status.config(text=f"复制失败：{exc}", fg=ERR)

    def _save(self):
        if not self._last_code:
            self._status.config(text="还没有生成注册码", fg=WARN)
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="保存注册码", defaultextension=".key",
            initialfile="customer.key",
            filetypes=[("注册码文件", "*.key *.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(self._last_code + "\n", encoding="utf-8")
            self._status.config(text=f"已保存：{path}", fg=OK)
        except Exception as exc:
            self._status.config(text=f"保存失败：{exc}", fg=ERR)

    def _clear(self):
        self._v_machine.set("")
        self._v_customer.set("")
        self._v_expires.set("")
        self._v_force.set(False)
        self._last_code = ""
        self._result.delete("1.0", tk.END)
        self._status.config(text="已清空。", fg=TEXT2)


def main():
    app = GeneratorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
