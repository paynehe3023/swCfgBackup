# -*- coding: utf-8 -*-
"""
网络设备配置备份工具 — GUI 版
基于 backup.py + inventory.py 的图形化前端
依赖：collector.py（同目录），paramiko，openpyxl
"""

import sys
import os
import ipaddress
import json
import re
import threading
import queue
import time
import webbrowser
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ------------------------------------------------------------------ #
#  依赖检查                                                            #
# ------------------------------------------------------------------ #
from utils import check_dependencies, get_app_dir
check_dependencies(gui=True)

# 应用程序所在目录（exe 模式下指向 exe 所在目录，脚本模式下指向脚本所在目录）
APP_DIR = get_app_dir()

# 导入备份逻辑（来自 backup.py + inventory.py）
try:
    if not getattr(sys, 'frozen', False):
        sys.path.insert(0, APP_DIR)
    from inventory import (load_from_excel, write_back_hostnames,
                           update_device_in_excel)
    from backup import (run_backup, backup_device, cleanup_old_backups,
                        generate_backup_report, select_retry_devices,
                        DEFAULT_RETRY_DELAY)
    from version import (APP_NAME, APP_VERSION, APP_AUTHOR, GITHUB_URL,
                         GITHUB_RELEASES_URL, GITHUB_LATEST_API,
                         is_newer_version)
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("模块缺失", f"找不到 backup.py、inventory.py 或 collector.py\n{e}")
    sys.exit(1)


# ================================================================== #
#  颜色 / 字体常量                                                     #
# ================================================================== #
C_BG        = "#1e2330"      # 主背景深蓝
C_SIDEBAR   = "#161b27"      # 侧栏更深
C_CARD      = "#252b3b"      # 卡片背景
C_ACCENT    = "#3b82f6"      # 蓝色强调
C_ACCENT2   = "#22c55e"      # 绿色成功
C_WARN      = "#f59e0b"      # 黄色警告
C_ERROR     = "#ef4444"      # 红色错误
C_TEXT      = "#e2e8f0"      # 主文本
C_TEXT2     = "#94a3b8"      # 次要文本
C_BORDER    = "#334155"      # 边框
C_ROW_ODD   = "#252b3b"
C_ROW_EVEN  = "#1e2330"
C_ROW_OK    = "#1a3a2a"
C_ROW_FAIL  = "#3a1a1a"
C_ROW_CHG   = "#3a3010"

FONT_TITLE  = ("Microsoft YaHei UI", 15, "bold")
FONT_HEAD   = ("Microsoft YaHei UI", 10, "bold")
FONT_BODY   = ("Microsoft YaHei UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_SMALL  = ("Microsoft YaHei UI", 8)
FONT_COUNT  = ("Microsoft YaHei UI", 20, "bold")


# ================================================================== #
#  主窗口                                                              #
# ================================================================== #
class BackupGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME}  v{APP_VERSION} by {APP_AUTHOR}")
        self.geometry("1080x720")
        self.minsize(900, 600)
        self.configure(bg=C_BG)

        # 图标：ico 用于标题栏/任务栏，png 供 Tk 与“关于”窗口使用
        try:
            base_path = getattr(sys, "_MEIPASS", APP_DIR)
            ico = os.path.join(base_path, "image", "icon.ico")
            png = os.path.join(base_path, "image", "icon.png")
            if os.path.isfile(ico):
                self.iconbitmap(ico)
            if os.path.isfile(png):
                self._window_icon = tk.PhotoImage(file=png)
                self.iconphoto(True, self._window_icon)
        except Exception:
            pass

        # 状态
        self._devices      = []       # 已加载的设备列表
        self._results      = []       # 本次备份结果
        self._running      = False    # 任务是否运行中
        self._log_queue    = queue.Queue()
        self._result_queue = queue.Queue()
        self._run_log_path = None      # 本次运行的自动日志文件
        self._log_lock     = threading.Lock()
        self._run_total    = 0         # 含补采的总任务数（进度条用）
        self._dev_editor   = None      # 设备清单就地编辑框
        self._dev_edit_ctx = None
        self._dirty_orig_ips = set()   # 尚未保存到 Excel 的设备（按原始 IP）
        self._single_running = False   # 单台备份是否进行中

        self._build_ui()
        self._poll_queues()

    # ---------------------------------------------------------------- #
    #  UI 构建                                                           #
    # ---------------------------------------------------------------- #
    def _build_ui(self):
        # ── 顶部标题栏 ──
        self._build_header()

        # ── 主体：左侧配置面板 + 右侧内容区 ──
        body = tk.Frame(self, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self._build_sidebar(body)
        self._build_content(body)

        # ── 底部状态栏 ──
        self._build_statusbar()

    # ---- 标题栏 ----
    def _build_header(self):
        bar = tk.Frame(self, bg=C_SIDEBAR, height=52)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        tk.Label(bar, text=f"🛡  {APP_NAME}",
                 font=FONT_TITLE, bg=C_SIDEBAR, fg=C_TEXT
                 ).pack(side=tk.LEFT, padx=20, pady=12)

        tk.Button(bar, text="关于", font=FONT_BODY, bg=C_SIDEBAR, fg=C_TEXT2,
                  activebackground=C_CARD, activeforeground=C_TEXT,
                  relief=tk.FLAT, bd=0, padx=10, cursor="hand2",
                  command=self._show_about
                  ).pack(side=tk.RIGHT, padx=(0, 6))

        self._lbl_time = tk.Label(bar, text="", font=FONT_BODY,
                                   bg=C_SIDEBAR, fg=C_TEXT2)
        self._lbl_time.pack(side=tk.RIGHT, padx=20)
        self._update_clock()

    def _update_clock(self):
        self._lbl_time.config(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        self.after(1000, self._update_clock)

    # ---------------------------------------------------------------- #
    #  关于 / 检查更新                                                    #
    # ---------------------------------------------------------------- #
    def _show_about(self):
        win = tk.Toplevel(self)
        win.title(f"关于 {APP_NAME}")
        win.configure(bg=C_BG)
        win.geometry("700x600")
        win.resizable(False, False)
        win.transient(self)
        try:
            base = getattr(sys, "_MEIPASS", APP_DIR)
            ico = os.path.join(base, "image", "icon.ico")
            if os.path.isfile(ico):
                win.iconbitmap(ico)
        except Exception:
            pass

        q = queue.Queue()
        state = {"busy": False, "asset": None,
                 "release_url": GITHUB_RELEASES_URL,
                 "download_path": "", "closed": False}
        ua = f"swCfgBackup/{APP_VERSION}"

        header = tk.Frame(win, bg=C_SIDEBAR)
        header.pack(fill=tk.X)
        try:
            base = getattr(sys, "_MEIPASS", APP_DIR)
            png = os.path.join(base, "image", "icon.png")
            photo = tk.PhotoImage(file=png)
            factor = max(1, photo.width() // 72)
            photo = photo.subsample(factor, factor)
            icon_lbl = tk.Label(header, image=photo, bg=C_SIDEBAR)
            icon_lbl.image = photo
            icon_lbl.pack(side=tk.LEFT, padx=(18, 12), pady=12)
        except Exception:
            pass
        title_box = tk.Frame(header, bg=C_SIDEBAR)
        title_box.pack(side=tk.LEFT, pady=12)
        tk.Label(title_box, text=APP_NAME, font=FONT_TITLE,
                 bg=C_SIDEBAR, fg=C_TEXT).pack(anchor="w")
        tk.Label(title_box, text=f"v{APP_VERSION}  ·  by {APP_AUTHOR}",
                 font=FONT_BODY, bg=C_SIDEBAR, fg=C_TEXT2).pack(anchor="w")

        body = tk.Frame(win, bg=C_BG)
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        link_row = tk.Frame(body, bg=C_BG)
        link_row.pack(fill=tk.X)
        tk.Button(link_row, text=GITHUB_URL, font=FONT_BODY, bg=C_BG,
                  fg=C_ACCENT, activebackground=C_BG, activeforeground=C_TEXT,
                  relief=tk.FLAT, bd=0, cursor="hand2",
                  command=lambda: webbrowser.open(GITHUB_URL)
                  ).pack(side=tk.LEFT)
        tk.Button(link_row, text="打开发布页", font=FONT_SMALL,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=8, pady=3, cursor="hand2",
                  command=lambda: webbrowser.open(GITHUB_RELEASES_URL)
                  ).pack(side=tk.RIGHT)
        tk.Button(link_row, text="打开仓库", font=FONT_SMALL,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=8, pady=3, cursor="hand2",
                  command=lambda: webbrowser.open(GITHUB_URL)
                  ).pack(side=tk.RIGHT, padx=6)

        tk.Frame(body, bg=C_BORDER, height=1).pack(fill=tk.X, pady=10)

        status_var = tk.StringVar(value="点击“检查更新”从 GitHub 获取最新版本")
        update_row = tk.Frame(body, bg=C_BG)
        update_row.pack(fill=tk.X)
        tk.Label(update_row, textvariable=status_var, font=FONT_BODY,
                 bg=C_BG, fg=C_TEXT2, anchor="w"
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        check_btn = tk.Button(update_row, text="检查更新", font=FONT_BODY,
                              bg=C_ACCENT, fg="white", relief=tk.FLAT, bd=0,
                              padx=10, pady=4, cursor="hand2",
                              command=lambda: check_update())
        check_btn.pack(side=tk.RIGHT)

        bar = ttk.Progressbar(body, mode="determinate", maximum=100)
        bar.pack(fill=tk.X, pady=(8, 8))

        notes = scrolledtext.ScrolledText(
            body, height=12, bg=C_SIDEBAR, fg=C_TEXT, font=FONT_MONO,
            insertbackground=C_TEXT, relief=tk.FLAT, bd=0, wrap=tk.WORD)
        notes.pack(fill=tk.BOTH, expand=True)
        notes.insert("1.0", f"{APP_NAME}\n版本：v{APP_VERSION}\n作者：{APP_AUTHOR}\n\n"
                            "点击“检查更新”查看 GitHub 上是否有新版本。")
        notes.config(state=tk.DISABLED)

        btn_row = tk.Frame(body, bg=C_BG)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        download_btn = tk.Button(btn_row, text="下载最新版本", font=FONT_BODY,
                                 bg=C_ACCENT2, fg="white", relief=tk.FLAT, bd=0,
                                 padx=10, pady=4, cursor="hand2", state=tk.DISABLED,
                                 command=lambda: download_update())
        download_btn.pack(side=tk.LEFT)
        open_folder_btn = tk.Button(btn_row, text="打开所在文件夹", font=FONT_BODY,
                                    bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                                    padx=10, pady=4, cursor="hand2",
                                    state=tk.DISABLED,
                                    command=lambda: open_folder())
        open_folder_btn.pack(side=tk.LEFT, padx=8)
        tk.Button(btn_row, text="关闭", font=FONT_BODY, bg=C_CARD, fg=C_TEXT,
                  relief=tk.FLAT, bd=0, padx=10, pady=4, cursor="hand2",
                  command=lambda: close()).pack(side=tk.RIGHT)

        def set_notes(text):
            notes.config(state=tk.NORMAL)
            notes.delete("1.0", tk.END)
            notes.insert("1.0", text)
            notes.config(state=tk.DISABLED)

        def set_busy(value):
            state["busy"] = value
            check_btn.config(state=tk.DISABLED if value else tk.NORMAL)
            download_btn.config(
                state=tk.NORMAL if (state["asset"] and not value) else tk.DISABLED)

        def pick_asset(assets):
            for suffix in (".exe", ".zip"):
                group = [a for a in assets
                         if str(a.get("name", "")).lower().endswith(suffix)]
                for a in group:
                    name = str(a.get("name", "")).lower()
                    if "win" in name or "x64" in name or "64" in name:
                        return a
                if group:
                    return group[0]
            return None

        def handle_release(data):
            tag = data.get("tag_name") or ""
            name = data.get("name") or tag
            body_text = data.get("body") or ""
            state["release_url"] = data.get("html_url") or GITHUB_RELEASES_URL
            state["asset"] = pick_asset(data.get("assets") or [])
            set_notes(f"{name}\n标签: {tag}\n\n{body_text}".strip()
                      or "该版本没有发布说明。")
            if is_newer_version(tag, APP_VERSION):
                status_var.set(f"发现新版本 {tag}（当前 v{APP_VERSION}）")
            else:
                status_var.set(f"当前已是最新版本（v{APP_VERSION}）")
            set_busy(False)
            if not state["asset"]:
                download_btn.config(state=tk.DISABLED)
                status_var.set(status_var.get() + "；该版本没有 exe/zip 附件")

        def check_update():
            if state["busy"]:
                return
            set_busy(True)
            status_var.set("正在检查 GitHub 最新版本...")
            bar.config(mode="determinate", maximum=100, value=0)
            threading.Thread(target=check_worker, daemon=True).start()

        def check_worker():
            try:
                req = urllib.request.Request(
                    GITHUB_LATEST_API,
                    headers={"User-Agent": ua,
                             "Accept": "application/vnd.github+json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                q.put(("release", data))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    q.put(("no_release", None))
                else:
                    q.put(("error", f"GitHub API 返回 {e.code} {e.reason}"))
            except Exception as e:
                q.put(("error", f"{type(e).__name__}: {e}"))

        def download_update():
            asset = state["asset"]
            if not asset:
                webbrowser.open(state["release_url"])
                return
            fname = re.sub(r'[<>:"/\\|?*]', "_",
                           str(asset.get("name") or "update.exe"))
            default_dir = Path.home() / "Downloads"
            if not default_dir.is_dir():
                default_dir = Path.cwd()
            path = filedialog.asksaveasfilename(
                parent=win, title="保存最新版本",
                initialdir=str(default_dir), initialfile=fname,
                filetypes=[("所有文件", "*.*")])
            if not path:
                return
            state["download_path"] = ""
            state["busy"] = True
            check_btn.config(state=tk.DISABLED)
            download_btn.config(state=tk.DISABLED)
            status_var.set("正在下载...")
            bar.config(mode="determinate", maximum=100, value=0)
            threading.Thread(target=download_worker,
                             args=(asset.get("browser_download_url"), path),
                             daemon=True).start()

        def download_worker(url, path):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": ua})
                with urllib.request.urlopen(req, timeout=60) as resp, \
                        open(path, "wb") as f:
                    total = int(resp.headers.get("Content-Length") or 0)
                    done = 0
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        q.put(("progress", (done, total)))
                q.put(("downloaded", path))
            except Exception as e:
                q.put(("download_error", f"{type(e).__name__}: {e}"))

        def open_folder():
            path = state.get("download_path")
            if not path:
                return
            try:
                os.startfile(str(Path(path).parent))
            except Exception as e:
                messagebox.showerror("打开失败", str(e), parent=win)

        def close():
            state["closed"] = True
            try:
                win.grab_release()
            except Exception:
                pass
            win.destroy()

        def poll():
            if state["closed"]:
                return
            try:
                while True:
                    kind, payload = q.get_nowait()
                    if kind == "release":
                        handle_release(payload)
                    elif kind == "no_release":
                        set_busy(False)
                        status_var.set("仓库还没有发布 Release 版本")
                        set_notes("暂无 Release。\n\n推送代码后，请在 GitHub 仓库的 "
                                  "Releases 页面创建标签（如 v0.0.1）并上传 exe/zip。")
                    elif kind == "error":
                        set_busy(False)
                        status_var.set(f"检查失败：{payload}")
                    elif kind == "progress":
                        done, total = payload
                        if total > 0:
                            bar.config(mode="determinate", maximum=total, value=done)
                            status_var.set(f"正在下载... {done / total * 100:.0f}%")
                        else:
                            status_var.set(f"正在下载... {done / 1048576:.1f} MB")
                    elif kind == "downloaded":
                        state["download_path"] = payload
                        set_busy(False)
                        bar.config(value=bar.cget("maximum"))
                        status_var.set(f"下载完成：{payload}")
                        open_folder_btn.config(state=tk.NORMAL)
                    elif kind == "download_error":
                        set_busy(False)
                        status_var.set(f"下载失败：{payload}")
            except queue.Empty:
                pass
            win.after(150, poll)

        win.protocol("WM_DELETE_WINDOW", close)
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.grab_set()
        win.after(150, poll)

    # ---- 侧边栏（参数配置） ----
    def _build_sidebar(self, parent):
        sb = tk.Frame(parent, bg=C_SIDEBAR, width=280)
        sb.pack(side=tk.LEFT, fill=tk.Y)
        sb.pack_propagate(False)

        def section(label):
            tk.Frame(sb, bg=C_BORDER, height=1).pack(fill=tk.X, padx=12, pady=(14,2))
            tk.Label(sb, text=label, font=FONT_SMALL, bg=C_SIDEBAR,
                     fg=C_ACCENT).pack(anchor=tk.W, padx=14, pady=(2,4))

        def lbl(text):
            tk.Label(sb, text=text, font=FONT_BODY, bg=C_SIDEBAR, fg=C_TEXT2
                     ).pack(anchor=tk.W, padx=16, pady=(4,1))

        def entry(var, **kw):
            e = tk.Entry(sb, textvariable=var, font=FONT_BODY,
                         bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
                         relief=tk.FLAT, bd=0, highlightthickness=1,
                         highlightcolor=C_ACCENT,
                         highlightbackground=C_BORDER, **kw)
            e.pack(fill=tk.X, padx=16, pady=(0,2))
            return e

        # ── 设备清单 ──
        section("📋  设备清单")
        lbl("Excel 文件路径")
        self._v_inv = tk.StringVar(value=os.path.join(APP_DIR, "pw.xlsx"))
        row = tk.Frame(sb, bg=C_SIDEBAR)
        row.pack(fill=tk.X, padx=16, pady=(0,2))
        tk.Entry(row, textvariable=self._v_inv, font=FONT_BODY,
                 bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
                 relief=tk.FLAT, bd=0, highlightthickness=1,
                 highlightcolor=C_ACCENT,
                 highlightbackground=C_BORDER
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(row, text="…", font=FONT_SMALL, bg=C_ACCENT, fg="white",
                  relief=tk.FLAT, bd=0, padx=6,
                  command=self._browse_inv
                  ).pack(side=tk.RIGHT, padx=(4,0))

        lbl("Sheet 名（留空=第一个）")
        self._v_sheet = tk.StringVar()
        entry(self._v_sheet)

        btn_row = tk.Frame(sb, bg=C_SIDEBAR)
        btn_row.pack(fill=tk.X, padx=16, pady=6)
        tk.Button(btn_row, text="📂 加载清单",
                  font=FONT_HEAD, bg=C_ACCENT, fg="white",
                  relief=tk.FLAT, bd=0, padx=8, pady=6,
                  cursor="hand2",
                  command=self._load_devices
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,4))
        tk.Button(btn_row, text="📄 生成模板",
                  font=FONT_HEAD, bg="#475569", fg="white",
                  relief=tk.FLAT, bd=0, padx=8, pady=6,
                  cursor="hand2",
                  command=self._generate_template
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._lbl_dev_count = tk.Label(sb, text="尚未加载", font=FONT_SMALL,
                                        bg=C_SIDEBAR, fg=C_TEXT2)
        self._lbl_dev_count.pack(anchor=tk.W, padx=16)

        # ── 备份选项 ──
        section("⚙️  备份选项")
        lbl("备份目录")
        self._v_bkdir = tk.StringVar(value=os.path.join(APP_DIR, "backup"))
        row2 = tk.Frame(sb, bg=C_SIDEBAR)
        row2.pack(fill=tk.X, padx=16, pady=(0,2))
        tk.Entry(row2, textvariable=self._v_bkdir, font=FONT_BODY,
                 bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
                 relief=tk.FLAT, bd=0, highlightthickness=1,
                 highlightcolor=C_ACCENT, highlightbackground=C_BORDER
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(row2, text="…", font=FONT_SMALL, bg=C_ACCENT, fg="white",
                  relief=tk.FLAT, bd=0, padx=6,
                  command=self._browse_bkdir
                  ).pack(side=tk.RIGHT, padx=(4,0))

        lbl("每设备保留份数")
        self._v_keepcount = tk.IntVar(value=1)
        tk.Spinbox(sb, from_=1, to=99, textvariable=self._v_keepcount,
                   font=FONT_BODY, bg=C_CARD, fg=C_TEXT,
                   insertbackground=C_TEXT, relief=tk.FLAT, bd=0,
                   buttonbackground=C_BORDER, width=8
                   ).pack(anchor=tk.W, padx=16, pady=(0,2))

        self._v_retry_auth = tk.BooleanVar(value=False)
        tk.Checkbutton(sb, text="认证失败也补采一次（有锁号风险）",
                       variable=self._v_retry_auth,
                       font=FONT_SMALL, bg=C_SIDEBAR, fg=C_TEXT2,
                       selectcolor=C_CARD, activebackground=C_SIDEBAR,
                       activeforeground=C_TEXT, anchor=tk.W
                       ).pack(anchor=tk.W, padx=12, pady=(0,2))

        lbl("并发线程数")
        self._v_conc = tk.IntVar(value=3)
        tk.Spinbox(sb, from_=1, to=10, textvariable=self._v_conc,
                   font=FONT_BODY, bg=C_CARD, fg=C_TEXT,
                   insertbackground=C_TEXT, relief=tk.FLAT, bd=0,
                   buttonbackground=C_BORDER, width=8
                   ).pack(anchor=tk.W, padx=16, pady=(0,2))

        # ── 启动按钮 ──
        tk.Frame(sb, bg=C_BORDER, height=1).pack(fill=tk.X, padx=12, pady=12)

        self._btn_start = tk.Button(
            sb, text="  ▶  开始备份  ",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg=C_ACCENT2, fg="white", relief=tk.FLAT, bd=0,
            padx=10, pady=8, cursor="hand2",
            command=self._start_backup
        )
        self._btn_start.pack(fill=tk.X, padx=16, pady=(0,4))

        self._btn_stop = tk.Button(
            sb, text="  ⏹  终止  ",
            font=FONT_HEAD,
            bg=C_ERROR, fg="white", relief=tk.FLAT, bd=0,
            padx=10, pady=6,
            state=tk.DISABLED,
            command=self._stop_backup
        )
        self._btn_stop.pack(fill=tk.X, padx=16)

        # ── 进度显示 ──
        section("📊  进度")
        self._v_progress = tk.DoubleVar(value=0)
        self._progressbar = ttk.Progressbar(
            sb, variable=self._v_progress,
            maximum=100, length=240, mode="determinate"
        )
        self._progressbar.pack(padx=16, pady=(4,2), fill=tk.X)

        self._lbl_progress = tk.Label(sb, text="等待开始...",
                                       font=FONT_SMALL, bg=C_SIDEBAR, fg=C_TEXT2)
        self._lbl_progress.pack(anchor=tk.W, padx=16)

    # ---- 右侧内容区 ----
    def _build_content(self, parent):
        self._nb = ttk.Notebook(parent)
        self._nb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=0, pady=0)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook",       background=C_BG,     borderwidth=0)
        style.configure("TNotebook.Tab",   background=C_CARD,   foreground=C_TEXT2,
                         padding=[14,6],   font=FONT_BODY)
        style.map("TNotebook.Tab",
                  background=[("selected", C_ACCENT)],
                  foreground=[("selected", "white")])
        style.configure("TProgressbar",    troughcolor=C_CARD,
                         background=C_ACCENT, borderwidth=0, thickness=8)

        # Tab 1 — 概览面板
        self._tab_overview = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(self._tab_overview, text=" 📊 概览 ")
        self._build_overview(self._tab_overview)

        # Tab 2 — 结果表格
        self._tab_results = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(self._tab_results, text=" 📋 备份结果 ")
        self._build_results_table(self._tab_results)

        # Tab 3 — 实时日志
        self._tab_log = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(self._tab_log, text=" 📝 运行日志 ")
        self._build_log(self._tab_log)

        # Tab 4 — 设备列表
        self._tab_devices = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(self._tab_devices, text=" 🖥 设备清单 ")
        self._build_device_list(self._tab_devices)

        # Tab 5 — 单台备份
        self._tab_single = tk.Frame(self._nb, bg=C_BG)
        self._nb.add(self._tab_single, text=" 🧪 单台备份 ")
        self._build_single_backup(self._tab_single)

    # ---- Tab 1: 概览 ----
    def _build_overview(self, parent):
        parent.columnconfigure((0,1,2,3), weight=1, uniform="ov")

        cards_info = [
            ("_card_total",   "设备总数",  "0", C_ACCENT),
            ("_card_success", "备份成功",  "0", C_ACCENT2),
            ("_card_changed", "配置变更",  "0", C_WARN),
            ("_card_failed",  "备份失败",  "0", C_ERROR),
        ]

        for col, (attr, title, val, color) in enumerate(cards_info):
            card = tk.Frame(parent, bg=C_CARD, relief=tk.FLAT, bd=0)
            card.grid(row=0, column=col, padx=8, pady=12, sticky="nsew")

            tk.Frame(card, bg=color, height=3).pack(fill=tk.X)
            tk.Label(card, text=title, font=FONT_BODY, bg=C_CARD,
                     fg=C_TEXT2).pack(pady=(12, 2))
            lbl = tk.Label(card, text=val, font=FONT_COUNT,
                           bg=C_CARD, fg=color)
            lbl.pack(pady=(0, 12))
            setattr(self, attr, lbl)

        # 下半：最近备份日志摘要
        frame = tk.Frame(parent, bg=C_CARD)
        frame.grid(row=1, column=0, columnspan=4, padx=8, pady=(0,8), sticky="nsew")
        parent.rowconfigure(1, weight=1)

        tk.Label(frame, text="  最近备份记录", font=FONT_HEAD,
                 bg=C_CARD, fg=C_TEXT, anchor=tk.W
                 ).pack(fill=tk.X, pady=(8,2))
        tk.Frame(frame, bg=C_BORDER, height=1).pack(fill=tk.X, padx=8)

        self._overview_list = tk.Listbox(
            frame, bg=C_CARD, fg=C_TEXT, font=FONT_MONO,
            selectbackground=C_ACCENT, activestyle="none",
            relief=tk.FLAT, bd=0, highlightthickness=0
        )
        self._overview_list.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ---- Tab 2: 结果表格 ----
    def _build_results_table(self, parent):
        cols = ("ip","status","time","size","changed","diff","filename","error")
        heads = ("IP 地址","状态","备份时间","大小KB","变更","变更行数","文件名","错误信息")

        style = ttk.Style()
        style.configure("Results.Treeview",
                         background=C_ROW_ODD, fieldbackground=C_ROW_ODD,
                         foreground=C_TEXT, rowheight=24,
                         borderwidth=0, relief=tk.FLAT)
        style.configure("Results.Treeview.Heading",
                         background=C_SIDEBAR, foreground=C_TEXT,
                         font=FONT_HEAD, relief=tk.FLAT)
        style.map("Results.Treeview",
                  background=[("selected", C_ACCENT)])

        toolbar = tk.Frame(parent, bg=C_BG)
        toolbar.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(toolbar, text="导出 Excel 报告", font=FONT_BODY,
                  bg=C_ACCENT, fg="white", relief=tk.FLAT, bd=0,
                  padx=8, pady=4, cursor="hand2",
                  command=self._export_report
                  ).pack(side=tk.LEFT, padx=4)
        tk.Button(toolbar, text="打开备份目录", font=FONT_BODY,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=8, pady=4, cursor="hand2",
                  command=self._open_backup_dir
                  ).pack(side=tk.LEFT, padx=4)

        frame = tk.Frame(parent, bg=C_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))

        self._tree = ttk.Treeview(frame, columns=cols, show="headings",
                                   style="Results.Treeview")
        widths = [120, 80, 140, 70, 70, 70, 300, 200]
        for col, head, w in zip(cols, heads, widths):
            self._tree.heading(col, text=head)
            self._tree.column(col, width=w, minwidth=50)

        vsb = ttk.Scrollbar(frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._tree.tag_configure("ok",      background=C_ROW_OK,   foreground="#86efac")
        self._tree.tag_configure("fail",    background=C_ROW_FAIL, foreground="#fca5a5")
        self._tree.tag_configure("changed", background=C_ROW_CHG,  foreground="#fde68a")

        # 双击打开文件
        self._tree.bind("<Double-1>", self._on_tree_dclick)

    # ---- Tab 3: 日志 ----
    def _build_log(self, parent):
        toolbar = tk.Frame(parent, bg=C_BG)
        toolbar.pack(fill=tk.X, padx=8, pady=4)
        tk.Button(toolbar, text="清空日志", font=FONT_BODY,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=8, pady=4, cursor="hand2",
                  command=self._clear_log
                  ).pack(side=tk.RIGHT, padx=4)
        tk.Button(toolbar, text="保存日志", font=FONT_BODY,
                  bg=C_CARD, fg=C_TEXT, relief=tk.FLAT, bd=0,
                  padx=8, pady=4, cursor="hand2",
                  command=self._save_log
                  ).pack(side=tk.RIGHT, padx=4)

        self._log_text = scrolledtext.ScrolledText(
            parent, bg=C_SIDEBAR, fg=C_TEXT, font=FONT_MONO,
            insertbackground=C_TEXT, relief=tk.FLAT, bd=0,
            wrap=tk.WORD, state=tk.DISABLED
        )
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0,8))
        self._log_text.tag_configure("ok",   foreground=C_ACCENT2)
        self._log_text.tag_configure("fail", foreground=C_ERROR)
        self._log_text.tag_configure("warn", foreground=C_WARN)
        self._log_text.tag_configure("info", foreground=C_TEXT2)
        self._log_text.tag_configure("head", foreground=C_ACCENT, font=FONT_HEAD)

    # ---- Tab 4: 设备列表 ----
    def _build_device_list(self, parent):
        cols_d = ("ip","hostname","port")
        heads_d = ("IP 地址","主机名","端口")
        self._dev_cols = cols_d

        toolbar = tk.Frame(parent, bg=C_BG)
        toolbar.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(toolbar,
                 text="提示：单击已选中的行或双击单元格，可修改 IP / 主机名 / 端口",
                 font=FONT_SMALL, bg=C_BG, fg=C_TEXT2
                 ).pack(side=tk.LEFT)
        tk.Button(toolbar, text="💾 保存清单修改", font=FONT_SMALL,
                  bg="#475569", fg="white", relief=tk.FLAT, bd=0,
                  padx=8, pady=4, cursor="hand2",
                  command=self._save_dirty_devices
                  ).pack(side=tk.RIGHT)

        style = ttk.Style()
        style.configure("Dev.Treeview",
                         background=C_ROW_ODD, fieldbackground=C_ROW_ODD,
                         foreground=C_TEXT, rowheight=22,
                         borderwidth=0, relief=tk.FLAT)
        style.configure("Dev.Treeview.Heading",
                         background=C_SIDEBAR, foreground=C_TEXT,
                         font=FONT_HEAD, relief=tk.FLAT)
        style.map("Dev.Treeview",
                  background=[("selected", C_ACCENT)])

        frame = tk.Frame(parent, bg=C_BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._dev_tree = ttk.Treeview(frame, columns=cols_d, show="headings",
                                       style="Dev.Treeview")
        widths_d = [150, 200, 70]
        for col, head, w in zip(cols_d, heads_d, widths_d):
            self._dev_tree.heading(col, text=head)
            self._dev_tree.column(col, width=w, minwidth=50)

        vsb2 = ttk.Scrollbar(frame, orient="vertical",   command=self._dev_tree.yview)
        self._dev_tree.configure(yscrollcommand=vsb2.set)
        self._dev_tree.grid(row=0, column=0, sticky="nsew")
        vsb2.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._dev_tree.bind("<Double-1>", self._on_device_dclick)
        self._dev_tree.bind("<Button-1>", self._on_device_click, add="+")

    # ---- Tab 5: 单台备份 ----
    def _build_single_backup(self, parent):
        card = tk.Frame(parent, bg=C_CARD)
        card.pack(fill=tk.X, padx=24, pady=20)
        card.columnconfigure(1, weight=1)

        tk.Label(card, text="单台设备备份", font=FONT_TITLE,
                 bg=C_CARD, fg=C_TEXT
                 ).grid(row=0, column=0, columnspan=2, sticky="w",
                        padx=18, pady=(16, 4))
        tk.Label(card,
                 text="填写设备信息后执行一次只读配置备份，文件保存到左侧设置的备份目录。",
                 font=FONT_SMALL, bg=C_CARD, fg=C_TEXT2
                 ).grid(row=1, column=0, columnspan=2, sticky="w",
                        padx=18, pady=(0, 12))

        def add_row(row, label, widget):
            tk.Label(card, text=label, font=FONT_BODY, bg=C_CARD, fg=C_TEXT2
                     ).grid(row=row, column=0, sticky="e", padx=(18, 10), pady=4)
            widget.grid(row=row, column=1, sticky="w", padx=(0, 18), pady=4)

        def entry(var, **kw):
            return tk.Entry(card, textvariable=var, font=FONT_BODY,
                            bg=C_BG, fg=C_TEXT, insertbackground=C_TEXT,
                            relief=tk.FLAT, bd=0, highlightthickness=1,
                            highlightcolor=C_ACCENT,
                            highlightbackground=C_BORDER, **kw)

        self._v_s_ip = tk.StringVar()
        self._v_s_port = tk.IntVar(value=22)
        self._v_s_user = tk.StringVar()
        self._v_s_pwd = tk.StringVar()

        add_row(2, "IP 地址", entry(self._v_s_ip, width=30))
        add_row(3, "端口",
                tk.Spinbox(card, from_=1, to=65535, textvariable=self._v_s_port,
                           width=8, font=FONT_BODY, bg=C_BG, fg=C_TEXT,
                           insertbackground=C_TEXT, relief=tk.FLAT, bd=0,
                           buttonbackground=C_BORDER))
        add_row(4, "用户名", entry(self._v_s_user, width=30))
        add_row(5, "密码", entry(self._v_s_pwd, width=30, show="*"))

        self._btn_single = tk.Button(
            card, text="  ▶  开始单台备份  ",
            font=FONT_HEAD, bg=C_ACCENT2, fg="white",
            relief=tk.FLAT, bd=0, padx=12, pady=6, cursor="hand2",
            command=self._start_single_backup)
        self._btn_single.grid(row=6, column=0, columnspan=2, sticky="w",
                              padx=18, pady=(12, 6))

        self._v_single_result = tk.StringVar(value="等待开始...")
        tk.Label(card, textvariable=self._v_single_result, font=FONT_BODY,
                 bg=C_CARD, fg=C_TEXT, anchor="w", justify="left",
                 wraplength=720
                 ).grid(row=7, column=0, columnspan=2, sticky="w",
                        padx=18, pady=(4, 4))
        tk.Label(card,
                 text="只读操作：仅执行 display current-configuration，不修改设备配置；"
                      "不会写入 Excel 清单。",
                 font=FONT_SMALL, bg=C_CARD, fg=C_TEXT2
                 ).grid(row=8, column=0, columnspan=2, sticky="w",
                        padx=18, pady=(0, 16))

    # ---- 底部状态栏 ----
    def _build_statusbar(self):
        bar = tk.Frame(self, bg=C_SIDEBAR, height=26)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        self._lbl_status = tk.Label(
            bar, text="  就绪", font=FONT_SMALL,
            bg=C_SIDEBAR, fg=C_TEXT2, anchor=tk.W
        )
        self._lbl_status.pack(side=tk.LEFT, fill=tk.X, padx=8)
        tk.Label(bar, text="  备份目录:", font=FONT_SMALL,
                 bg=C_SIDEBAR, fg=C_TEXT2).pack(side=tk.RIGHT, padx=(0,4))
        self._lbl_bkdir_status = tk.Label(bar, text="", font=FONT_SMALL,
                                           bg=C_SIDEBAR, fg=C_ACCENT2, anchor=tk.E)
        self._lbl_bkdir_status.pack(side=tk.RIGHT)

    # ================================================================ #
    #  按钮状态统一管理                                                  #
    # ================================================================ #
    def _set_btn_state(self, running: bool):
        """
        running=True  → 备份进行中：开始按钮禁用（灰色），终止按钮激活（红色）
        running=False → 空闲/完成：开始按钮激活（绿色），终止按钮禁用（灰色）
        """
        if running:
            self._btn_start.config(
                state=tk.DISABLED,
                bg="#4b5563",       # 灰色
                fg="#9ca3af",
                cursor=""
            )
            self._btn_stop.config(
                state=tk.NORMAL,
                bg=C_ERROR,         # 红色
                fg="white",
                cursor="hand2"
            )
        else:
            self._btn_start.config(
                state=tk.NORMAL,
                bg=C_ACCENT2,       # 绿色
                fg="white",
                cursor="hand2"
            )
            self._btn_stop.config(
                state=tk.DISABLED,
                bg="#4b5563",       # 灰色
                fg="#9ca3af",
                cursor=""
            )

    # ================================================================ #
    #  事件处理                                                          #
    # ================================================================ #
    def _browse_inv(self):
        p = filedialog.askopenfilename(
            title="选择设备清单 Excel",
            filetypes=[("Excel 文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if p:
            self._v_inv.set(p)

    def _browse_bkdir(self):
        p = filedialog.askdirectory(title="选择备份存储目录")
        if p:
            self._v_bkdir.set(p)

    def _generate_template(self):
        """生成标准设备清单 Excel 模板，并询问保存路径"""
        path = filedialog.asksaveasfilename(
            title="保存设备清单模板",
            defaultextension=".xlsx",
            initialfile="设备清单模板.xlsx",
            filetypes=[("Excel 文件", "*.xlsx")]
        )
        if not path:
            return
        try:
            from inventory import create_excel_template
            create_excel_template(path)
            self._log(f"[模板] 已生成: {path}", "ok")
            self._set_status(f"模板已生成：{Path(path).name}")
            if messagebox.askyesno("生成成功", f"模板已保存：\n{path}\n\n是否立即打开？"):
                os.startfile(path)
        except Exception as e:
            messagebox.showerror("生成失败", str(e))
            self._log(f"[模板] 生成失败: {e}", "fail")

    def _load_devices(self):
        inv = self._v_inv.get().strip()
        if not inv:
            messagebox.showwarning("提示", "请先选择 Excel 设备清单文件")
            return
        if not Path(inv).exists():
            messagebox.showerror("错误", f"文件不存在：{inv}")
            return

        # 清空旧数据
        for item in self._dev_tree.get_children():
            self._dev_tree.delete(item)

        try:
            self._devices = load_from_excel(
                inv,
                sheet_name=self._v_sheet.get().strip() or None
            )
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return

        self._dirty_orig_ips = set()
        self._cancel_device_edit()

        for d in self._devices:
            self._dev_tree.insert("", "end", values=(
                d["ip"], d.get("hostname",""), d.get("port",22)
            ))

        count = len(self._devices)
        self._lbl_dev_count.config(
            text=f"已加载 {count} 台设备", fg=C_ACCENT2 if count else C_ERROR
        )
        self._card_total.config(text=str(count))
        self._set_status(f"设备清单加载完成：{count} 台设备")
        self._nb.select(self._tab_devices)
        self._log(f"[加载] {inv}  共 {count} 台设备", "ok")

    # ---------------------------------------------------------------- #
    #  设备清单就地编辑                                                   #
    # ---------------------------------------------------------------- #
    def _cell_col_index(self, x):
        col = self._dev_tree.identify_column(x)
        try:
            idx = int(col.replace("#", "")) - 1
        except Exception:
            return None
        return idx if 0 <= idx < len(self._dev_cols) else None

    def _on_device_click(self, event):
        """单击已选中的行进入编辑；未选中的行先让默认逻辑选中它"""
        if self._running or self._dev_editor is not None:
            return
        item = self._dev_tree.identify_row(event.y)
        if not item or item not in self._dev_tree.selection():
            return
        idx = self._cell_col_index(event.x)
        if idx is not None:
            self._begin_device_edit(item, idx)
            return "break"

    def _on_device_dclick(self, event):
        if self._running:
            return
        item = self._dev_tree.identify_row(event.y)
        idx = self._cell_col_index(event.x)
        if item and idx is not None:
            self._begin_device_edit(item, idx)
            return "break"

    def _begin_device_edit(self, item, col_idx):
        if self._running:
            self._set_status("备份进行中，暂不能修改设备清单")
            return
        self._cancel_device_edit()
        bbox = self._dev_tree.bbox(item, column=f"#{col_idx + 1}")
        if not bbox:
            return
        x, y, w, h = bbox
        values = list(self._dev_tree.item(item, "values"))
        cur = values[col_idx] if col_idx < len(values) else ""
        ed = tk.Entry(self._dev_tree, font=FONT_BODY,
                      bg=C_CARD, fg=C_TEXT, insertbackground=C_TEXT,
                      relief=tk.FLAT, highlightthickness=1,
                      highlightcolor=C_ACCENT, highlightbackground=C_ACCENT)
        ed.insert(0, str(cur))
        ed.place(x=x, y=y, width=max(w, 70), height=h)
        ed.focus_set()
        ed.select_range(0, tk.END)
        self._dev_editor = ed
        self._dev_edit_ctx = (item, col_idx)
        ed.bind("<Return>", lambda e: self._commit_device_edit())
        ed.bind("<Escape>", lambda e: self._cancel_device_edit())
        ed.bind("<FocusOut>", lambda e: self._commit_device_edit())

    def _cancel_device_edit(self):
        ed, self._dev_editor = self._dev_editor, None
        self._dev_edit_ctx = None
        if ed is not None:
            try:
                ed.destroy()
            except Exception:
                pass

    def _commit_device_edit(self):
        if self._dev_editor is None or self._dev_edit_ctx is None:
            return
        ed = self._dev_editor
        item, col_idx = self._dev_edit_ctx
        value = ed.get().strip()
        self._dev_editor = None
        self._dev_edit_ctx = None
        try:
            ed.destroy()
        except Exception:
            pass
        if self._dev_tree.exists(item):
            self._apply_device_edit(item, col_idx, value)

    def _refresh_device_row(self, item, dev):
        if self._dev_tree.exists(item):
            self._dev_tree.item(item, values=(
                dev["ip"], dev.get("hostname", ""), dev.get("port", 22)))

    def _apply_device_edit(self, item, col_idx, value):
        """把一次编辑应用到内存、界面，并尝试写回 Excel"""
        try:
            row_idx = self._dev_tree.index(item)
        except Exception:
            return
        if row_idx >= len(self._devices):
            return
        dev = self._devices[row_idx]
        field = self._dev_cols[col_idx]
        old = str(dev.get(field, ""))
        if value == old:
            return

        updates = {}
        if field == "port":
            try:
                port = int(value)
                if not (1 <= port <= 65535):
                    raise ValueError
            except Exception:
                messagebox.showwarning("端口无效", "端口必须是 1-65535 之间的整数")
                self._refresh_device_row(item, dev)
                return
            dev["port"] = port
            updates["port"] = port
        elif field == "ip":
            try:
                ipaddress.IPv4Address(value)
            except Exception:
                messagebox.showwarning("IP 无效", "请输入合法的 IPv4 地址")
                self._refresh_device_row(item, dev)
                return
            if any(d is not dev and str(d.get("ip", "")) == value
                   for d in self._devices):
                messagebox.showwarning("IP 重复", "清单中已存在该 IP 地址")
                self._refresh_device_row(item, dev)
                return
            dev["ip"] = value
            updates["ip"] = value
        else:
            dev["hostname"] = value
            updates["hostname"] = value

        self._refresh_device_row(item, dev)
        self._set_status(f"清单已修改：{dev['ip']}  {field}: {old} → {value}")

        orig_ip = dev.get("_orig_ip") or (old if field == "ip" else dev["ip"])
        inv = self._v_inv.get().strip()
        if not (inv and Path(inv).exists()):
            self._log(f"[清单] 已修改 {dev['ip']} 的 {field}（仅本次运行生效）", "warn")
            return

        sheet = self._v_sheet.get().strip() or None
        info = update_device_in_excel(inv, orig_ip, updates, sheet)
        if info["error"]:
            self._dirty_orig_ips.add(orig_ip)
            self._log(f"[清单] 修改已生效，但写回 Excel 失败: {info['error']}", "warn")
        else:
            if field == "ip":
                dev["_orig_ip"] = dev["ip"]
            self._dirty_orig_ips.discard(orig_ip)
            self._log(f"[清单] 已修改 {dev['ip']} 的 {field} 并写入 Excel", "ok")

    def _save_dirty_devices(self, silent=False):
        """把尚未写入 Excel 的清单修改一次性保存"""
        if self._running:
            if not silent:
                self._set_status("备份进行中，暂不能保存清单")
            return False
        inv = self._v_inv.get().strip()
        if not inv or not Path(inv).exists():
            if not silent:
                messagebox.showwarning("提示", "请先加载设备清单")
            return False
        if not self._dirty_orig_ips:
            if not silent:
                self._set_status("清单没有未保存的修改")
            return True

        sheet = self._v_sheet.get().strip() or None
        saved = failed = 0
        for orig_ip in list(self._dirty_orig_ips):
            dev = next((d for d in self._devices
                        if str(d.get("_orig_ip", "")) == orig_ip), None)
            if dev is None:
                self._dirty_orig_ips.discard(orig_ip)
                continue
            updates = {"ip": dev["ip"],
                       "hostname": dev.get("hostname", ""),
                       "port": dev.get("port", 22)}
            info = update_device_in_excel(inv, orig_ip, updates, sheet)
            if info["error"]:
                failed += 1
                self._log(f"[清单] 保存失败 {orig_ip}: {info['error']}", "warn")
            else:
                saved += 1
                self._dirty_orig_ips.discard(orig_ip)
                dev["_orig_ip"] = dev["ip"]
        if saved:
            self._log(f"[清单] 已保存 {saved} 台设备的修改到 {inv}", "ok")
        if failed:
            self._log(f"[清单] {failed} 台设备的修改未能保存（请关闭 Excel 后重试）", "warn")
            if not silent:
                messagebox.showwarning(
                    "保存失败",
                    f"{failed} 台设备的修改未能保存，请关闭该 Excel 文件后重试。")
            return False
        if not silent:
            self._set_status(f"清单修改已保存（{saved} 台）")
        return True

    def _start_backup(self):
        if not self._devices:
            messagebox.showwarning("提示", "请先加载设备清单")
            return
        if self._running:
            return
        if self._single_running:
            messagebox.showwarning("提示", "单台备份正在进行，请稍后再试")
            return
        if self._dirty_orig_ips:
            self._save_dirty_devices(silent=True)

        # 清空旧结果
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._results = []
        self._card_success.config(text="0")
        self._card_changed.config(text="0")
        self._card_failed.config(text="0")
        self._overview_list.delete(0, tk.END)

        self._running   = True
        self._stop_flag = False
        self._set_btn_state(running=True)
        self._btn_single.config(state=tk.DISABLED, bg="#4b5563",
                                fg="#9ca3af", cursor="")
        self._v_progress.set(0)
        self._lbl_progress.config(text="准备中...")
        self._nb.select(self._tab_log)

        bkdir = self._v_bkdir.get().strip() or "backup"
        keep_count = self._v_keepcount.get()
        conc  = self._v_conc.get()
        retry_auth = self._v_retry_auth.get()

        # 本次运行的自动日志文件（备份目录下）
        self._run_log_path = None
        self._run_total = 0
        try:
            Path(bkdir).mkdir(parents=True, exist_ok=True)
            self._run_log_path = (Path(bkdir) /
                                  f"backup_log_{datetime.now():%Y%m%d_%H%M%S}.txt")
        except Exception:
            self._run_log_path = None

        self._lbl_bkdir_status.config(text=bkdir)
        self._log(f"{'='*52}", "head")
        self._log(f"  备份任务启动  {datetime.now():%Y-%m-%d %H:%M:%S}", "head")
        self._log(f"  设备数: {len(self._devices)}  并发: {conc}  "
                  f"保留: 最近 {keep_count} 份", "info")
        self._log(f"  备份目录: {bkdir}", "info")
        self._log(
            f"  失败补采: {'启用（含认证失败）' if retry_auth else '启用（跳过认证失败）'}",
            "info")
        self._log(f"{'='*52}", "head")

        inv_path = self._v_inv.get().strip()
        sheet = self._v_sheet.get().strip() or None

        t = threading.Thread(
            target=self._backup_worker,
            args=(self._devices, bkdir, conc, keep_count, retry_auth,
                  inv_path, sheet),
            daemon=True
        )
        t.start()

    # ---------------------------------------------------------------- #
    #  单台设备备份                                                       #
    # ---------------------------------------------------------------- #
    def _start_single_backup(self):
        if self._running or self._single_running:
            messagebox.showwarning("提示", "已有备份任务在进行，请稍后再试")
            return

        ip = self._v_s_ip.get().strip()
        try:
            ipaddress.IPv4Address(ip)
        except Exception:
            messagebox.showwarning("IP 无效", "请输入合法的 IPv4 地址")
            return
        try:
            port = int(self._v_s_port.get())
            if not (1 <= port <= 65535):
                raise ValueError
        except Exception:
            messagebox.showwarning("端口无效", "端口必须是 1-65535 之间的整数")
            return
        username = self._v_s_user.get().strip()
        password = self._v_s_pwd.get()
        if not username or not password:
            messagebox.showwarning("信息不完整", "请填写用户名和密码")
            return

        bkdir = self._v_bkdir.get().strip() or "backup"
        try:
            Path(bkdir).mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("目录错误", f"无法创建备份目录：{e}")
            return

        # 单台备份也生成一份自动日志
        try:
            self._run_log_path = (Path(bkdir) /
                                  f"backup_log_{datetime.now():%Y%m%d_%H%M%S}.txt")
        except Exception:
            self._run_log_path = None

        self._single_running = True
        self._btn_single.config(state=tk.DISABLED, bg="#4b5563",
                                fg="#9ca3af", cursor="")
        self._v_single_result.set(f"正在备份 {ip}:{port} ...")
        self._log(f"{'='*52}", "head")
        self._log(f"  单台备份启动  {ip}:{port}  "
                  f"{datetime.now():%Y-%m-%d %H:%M:%S}", "head")
        self._set_status(f"单台备份进行中：{ip}:{port}")

        threading.Thread(
            target=self._single_worker,
            args=(ip, port, username, password, bkdir),
            daemon=True,
        ).start()

    def _single_worker(self, ip, port, username, password, bkdir):
        try:
            r = backup_device(ip, username, password, port, "auto", bkdir)
        except Exception as e:
            r = {"ip": ip, "sysname": "", "status": "failed", "error": str(e),
                 "changed": False, "diff_lines": 0, "size_kb": 0, "filename": "",
                 "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        self._result_queue.put(("single_done", r))

    def _stop_backup(self):
        self._stop_flag = True
        self._log("[停止] 已发送停止信号，等待当前任务完成...", "warn")
        # 终止按钮立即禁用（防止重复点击），开始按钮等任务真正结束后再恢复
        self._btn_stop.config(state=tk.DISABLED, bg="#4b5563", fg="#9ca3af", cursor="")

    def _backup_worker(self, devices, bkdir, conc, keep_count, retry_auth,
                       inv_path="", sheet=None):
        import concurrent.futures
        from pathlib import Path as _Path

        total = len(devices)
        done = 0
        by_ip = {}

        _Path(bkdir).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        def make_result(dev, error=""):
            return {
                "ip": dev["ip"], "status": "failed", "error": error,
                "changed": False, "diff_lines": 0, "size_kb": 0,
                "filename": "",
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        def run_pass(dev_list):
            nonlocal done
            with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as executor:
                futures = {
                    executor.submit(
                        backup_device,
                        d["ip"], d["username"], d["password"],
                        d.get("port", 22), d.get("vendor", "auto"),
                        bkdir, "", 0
                    ): d
                    for d in dev_list
                }
                for future in concurrent.futures.as_completed(futures):
                    if self._stop_flag:
                        for f in futures:
                            f.cancel()
                        break
                    try:
                        r = future.result()
                    except Exception as e:
                        r = make_result(futures[future], str(e))

                    by_ip[r["ip"]] = r
                    done += 1
                    self._result_queue.put(("progress", done / total * 100,
                                            done, total))
                    self._result_queue.put(("row", r))

        run_pass(devices)
        results = list(by_ip.values())

        # ---------- 失败补采 ----------
        if not self._stop_flag:
            retry_devs = select_retry_devices(devices, results, retry_auth)
            if retry_devs:
                self._result_queue.put((
                    "log",
                    f"[补采] {len(retry_devs)} 台失败设备将在 "
                    f"{DEFAULT_RETRY_DELAY} 秒后重试一次",
                    "warn"))
                self._result_queue.put(("retry_start", len(retry_devs), total))
                for _ in range(int(DEFAULT_RETRY_DELAY)):
                    if self._stop_flag:
                        break
                    time.sleep(1)

                if not self._stop_flag:
                    retry_total = len(retry_devs)
                    retry_done = 0
                    with concurrent.futures.ThreadPoolExecutor(max_workers=conc) as executor:
                        futures = {
                            executor.submit(
                                backup_device,
                                d["ip"], d["username"], d["password"],
                                d.get("port", 22), d.get("vendor", "auto"),
                                bkdir, "", 0
                            ): d
                            for d in retry_devs
                        }
                        for future in concurrent.futures.as_completed(futures):
                            if self._stop_flag:
                                for f in futures:
                                    f.cancel()
                                break
                            try:
                                r = future.result()
                            except Exception as e:
                                r = make_result(futures[future], str(e))

                            by_ip[r["ip"]] = r
                            retry_done += 1
                            self._result_queue.put(("retry_progress",
                                                    retry_done, retry_total))

                            if "success" in r["status"]:
                                chg = (f" [{r.get('diff_lines', 0)} 行变更]"
                                       if r.get("changed") else " [无变更]")
                                self._result_queue.put((
                                    "log",
                                    f"  ✓ {r['ip']} 补采成功  "
                                    f"{float(r.get('size_kb') or 0):.1f}KB{chg}",
                                    "ok"))
                            else:
                                self._result_queue.put((
                                    "log",
                                    f"  ✗ {r['ip']} 补采仍失败: "
                                    f"{r.get('error', '')}",
                                    "fail"))

        results = list(by_ip.values())
        results.sort(key=lambda r: [int(x) for x in r["ip"].split(".") if x.isdigit()])

        # 补采会覆盖第一轮的失败行：用最终结果重建表格
        self._result_queue.put(("replace_all", results))

        # 清理旧备份
        cleanup_old_backups(bkdir, keep_count)

        # 生成报告
        report_path = str(_Path(bkdir) / f"backup_report_{timestamp}.xlsx")
        try:
            generate_backup_report(results, report_path)
            self._result_queue.put(("report", report_path))
        except Exception as e:
            self._result_queue.put(("log", f"[报告] 生成失败: {e}", "fail"))

        # 主机名回填 Excel（只填空单元格，不覆盖手工维护的值）
        hostmap = {r["ip"]: r.get("sysname", "")
                   for r in results if "success" in r["status"]}
        hostmap = {ip: name for ip, name in hostmap.items() if name}
        if hostmap:
            for d in devices:
                # 与回填规则保持一致：只补空值，不覆盖已维护的主机名
                if not str(d.get("hostname") or "").strip() and hostmap.get(d["ip"]):
                    d["hostname"] = hostmap[d["ip"]]
        if inv_path and hostmap:
            info = write_back_hostnames(inv_path, hostmap, sheet)
            if info["error"]:
                self._result_queue.put(
                    ("log", f"[主机名] 回填失败: {info['error']}", "fail"))
            else:
                self._result_queue.put((
                    "log",
                    f"[主机名] 已回填 {info['filled']} 台到 {inv_path}"
                    f"（保留已有值 {info['skipped']} 台）", "ok"))
        if hostmap:
            self._result_queue.put(("devices_refresh", devices))

        self._result_queue.put(("done", results))

    def _export_report(self):
        if not self._results:
            messagebox.showinfo("提示", "暂无备份结果，请先执行备份")
            return
        path = filedialog.asksaveasfilename(
            title="保存备份报告",
            defaultextension=".xlsx",
            initialfile=f"backup_report_{datetime.now():%Y%m%d_%H%M%S}.xlsx",
            filetypes=[("Excel 文件","*.xlsx")]
        )
        if path:
            try:
                generate_backup_report(self._results, path)
                messagebox.showinfo("完成", f"报告已保存：\n{path}")
            except Exception as e:
                messagebox.showerror("失败", str(e))

    def _open_backup_dir(self):
        d = self._v_bkdir.get().strip() or "backup"
        p = Path(d)
        if p.exists():
            os.startfile(str(p))
        else:
            messagebox.showwarning("提示", f"目录不存在：{p}")

    def _on_tree_dclick(self, event):
        sel = self._tree.selection()
        if not sel:
            return
        vals = self._tree.item(sel[0], "values")
        fname = vals[6] if len(vals) > 6 else ""
        if fname and fname != "-":
            bkdir = self._v_bkdir.get().strip() or "backup"
            # 文件名格式 {ip}_{date}_{ts}_{hash}.txt
            ip = vals[0]
            fpath = Path(bkdir) / ip / fname
            if fpath.exists():
                os.startfile(str(fpath))
            else:
                messagebox.showinfo("提示", f"文件不存在：{fpath}")

    def _clear_log(self):
        """清空界面日志、尚未显示的日志队列，以及本次运行的日志文件"""
        try:
            while True:
                self._log_queue.get_nowait()
        except queue.Empty:
            pass
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete("1.0", tk.END)
        self._log_text.config(state=tk.DISABLED)
        p = getattr(self, "_run_log_path", None)
        if p:
            try:
                with self._log_lock:
                    with open(str(p), "w", encoding="utf-8"):
                        pass
            except Exception:
                pass
        self._set_status("日志已清空")

    def _save_log(self):
        path = filedialog.asksaveasfilename(
            title="保存日志",
            defaultextension=".txt",
            initialfile=f"backup_log_{datetime.now():%Y%m%d_%H%M%S}.txt",
            filetypes=[("文本文件","*.txt")]
        )
        if path:
            try:
                content = self._log_text.get("1.0", tk.END)
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                messagebox.showinfo("完成", f"日志已保存：\n{path}")
            except Exception as e:
                messagebox.showerror("失败", str(e))

    # ================================================================ #
    #  辅助方法                                                          #
    # ================================================================ #
    def _log(self, msg: str, tag: str = ""):
        """写入界面日志队列，同时追加到本次运行的自动日志文件"""
        self._log_queue.put((msg, tag))
        p = getattr(self, "_run_log_path", None)
        if p:
            try:
                line = f"[{datetime.now():%H:%M:%S}] {msg}\n"
                with self._log_lock:
                    with open(str(p), "a", encoding="utf-8") as f:
                        f.write(line)
            except Exception:
                pass

    def _set_status(self, msg: str):
        self._lbl_status.config(text=f"  {msg}")

    def _apply_result(self, r, log=True):
        """把一条结果写入结果表格、概览列表和统计卡片"""
        status_ok = "success" in r["status"]
        status_txt = "✓ 成功" if status_ok else "✗ 失败"
        chg_txt = "⚠ 变更" if r.get("changed") else ("✓ 无变更" if status_ok else "-")

        if not status_ok:
            tag = "fail"
        elif r.get("changed"):
            tag = "changed"
        else:
            tag = "ok"

        self._tree.insert("", "end", values=(
            r["ip"], status_txt, r.get("timestamp", ""),
            r.get("size_kb", "-"), chg_txt,
            r.get("diff_lines", "-"), r.get("filename", "-"),
            r.get("error", "")
        ), tags=(tag,))

        if log:
            if status_ok:
                chg = (f" [{r.get('diff_lines', 0)} 行变更]"
                       if r.get("changed") else " [无变更]")
                self._log(f"  ✓ {r['ip']}  "
                          f"{float(r.get('size_kb') or 0):.1f}KB{chg}", "ok")
            else:
                self._log(f"  ✗ {r['ip']}  {r.get('error', '')}", "fail")

        self._results.append(r)
        self._overview_list.insert(
            0,
            f"{'✓' if status_ok else '✗'}  {r['ip']:<18} {status_txt}  {chg_txt}"
        )
        self._refresh_cards()

    def _refresh_cards(self):
        ok = sum(1 for x in self._results if "success" in x["status"])
        chg = sum(1 for x in self._results if x.get("changed"))
        fail = len(self._results) - ok
        self._card_success.config(text=str(ok))
        self._card_changed.config(text=str(chg))
        self._card_failed.config(text=str(fail))

    def _poll_queues(self):
        """主线程轮询消息队列，更新 UI"""
        # 处理日志
        try:
            while True:
                msg, tag = self._log_queue.get_nowait()
                self._log_text.config(state=tk.NORMAL)
                ts = datetime.now().strftime("%H:%M:%S")
                self._log_text.insert(tk.END, f"[{ts}] {msg}\n", tag or None)
                self._log_text.see(tk.END)
                self._log_text.config(state=tk.DISABLED)
        except queue.Empty:
            pass

        # 处理结果
        try:
            while True:
                item = self._result_queue.get_nowait()
                kind = item[0]

                if kind == "progress":
                    _, pct, done, total = item
                    self._v_progress.set(pct)
                    self._lbl_progress.config(text=f"{done}/{total}  ({pct:.0f}%)")
                    self._set_status(f"备份进行中... {done}/{total}")

                elif kind == "row":
                    self._apply_result(item[1], log=True)

                elif kind == "retry_start":
                    _, n_retry, total_devices = item
                    self._run_total = total_devices + n_retry
                    self._v_progress.set(total_devices / self._run_total * 100)
                    self._lbl_progress.config(text=f"补采 0/{n_retry}")
                    self._set_status(f"失败补采：{n_retry} 台，等待重试...")

                elif kind == "retry_progress":
                    _, done_retry, total_retry = item
                    if self._run_total:
                        overall = (self._run_total - total_retry) + done_retry
                        self._v_progress.set(overall / self._run_total * 100)
                    self._lbl_progress.config(
                        text=f"补采 {done_retry}/{total_retry}")

                elif kind == "replace_all":
                    # 补采结果覆盖第一轮失败行：按最终结果重建表格
                    for i in self._tree.get_children():
                        self._tree.delete(i)
                    self._overview_list.delete(0, tk.END)
                    self._results = []
                    for r in item[1]:
                        self._apply_result(r, log=False)

                elif kind == "devices_refresh":
                    for i in self._dev_tree.get_children():
                        self._dev_tree.delete(i)
                    for d in item[1]:
                        self._dev_tree.insert("", "end", values=(
                            d["ip"], d.get("hostname", ""), d.get("port", 22)))

                elif kind == "single_done":
                    r = item[1]
                    self._single_running = False
                    self._btn_single.config(state=tk.NORMAL, bg=C_ACCENT2,
                                            fg="white", cursor="hand2")
                    if "success" in r["status"]:
                        self._v_single_result.set(
                            f"成功：{r.get('sysname') or '-'}  "
                            f"{float(r.get('size_kb') or 0):.1f}KB\n"
                            f"文件：{r.get('filename')}")
                        self._log(
                            f"[单台] ✓ {r['ip']}  "
                            f"{float(r.get('size_kb') or 0):.1f}KB  "
                            f"{r.get('filename')}", "ok")
                    else:
                        self._v_single_result.set(f"失败：{r.get('error', '')}")
                        self._log(f"[单台] ✗ {r['ip']}  {r.get('error','')}", "fail")
                    if self._run_log_path:
                        self._log(f"[日志] 已自动保存: {self._run_log_path}", "info")
                    self._set_status(f"单台备份完成：{r['ip']}")

                elif kind == "report":
                    report_path = item[1]
                    self._log(f"[报告] 已生成: {report_path}", "ok")

                elif kind == "log":
                    _, msg, tag = item
                    self._log(msg, tag)

                elif kind == "done":
                    results = item[1]
                    ok   = sum(1 for r in results if "success" in r["status"])
                    fail = len(results) - ok
                    chg  = sum(1 for r in results if r.get("changed"))
                    self._running = False
                    self._set_btn_state(running=False)
                    self._btn_single.config(state=tk.NORMAL, bg=C_ACCENT2,
                                            fg="white", cursor="hand2")
                    self._v_progress.set(100)
                    self._lbl_progress.config(text="完成")
                    self._set_status(
                        f"备份完成！成功 {ok}/{len(results)}  变更 {chg} 台  失败 {fail} 台"
                    )
                    self._log(f"{'='*52}", "head")
                    self._log(
                        f"  备份完成  成功:{ok}  变更:{chg}  失败:{fail}  共:{len(results)}",
                        "head"
                    )
                    self._log(f"{'='*52}", "head")
                    if self._run_log_path:
                        self._log(f"[日志] 已自动保存: {self._run_log_path}", "info")
                    self._nb.select(self._tab_overview)

        except queue.Empty:
            pass

        self.after(80, self._poll_queues)


# ================================================================== #
#  入口                                                                #
# ================================================================== #
def main():
    if sys.platform == "win32":
        try:
            import ctypes
            # 让任务栏使用本程序的图标与分组，而不是 python/默认图标
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"payne.swCfgBackup.{APP_VERSION}")
        except Exception:
            pass
    app = BackupGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
