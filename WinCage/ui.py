"""WinCage - Windows 8 磁贴风格 UI（Tkinter，零第三方依赖）。"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import tkinter.filedialog as filedialog
import tkinter.messagebox as messagebox
from queue import Queue

from core import BUS, APP_NAME, APP_VERSION, IS_WIN, is_admin, open_path, human_size
from config import (
    Container, KIND_SANDBOX, KIND_VM, KIND_APP, KIND_PLAIN,
    MODE_AUTO, MODE_SANDBOX, MODE_VM, MODE_APP, MODE_PLAIN,
    TARGET_EXE, TARGET_MSIX, TARGET_INSTALLER,
    detect_target_type, next_color, load, save,
)
import engine

# 两套主题：Win8 磁贴经典深色 + 清爽亮色
DARK = dict(
    BG="#16181C", PANEL="#101216", INK="#FFFFFF", INK_DIM="#B7BEC7",
    INK_MUTE="#7A8290", ACCENT="#0B78D0", LINE="#262A31",
    BTN="#252A32", BTN_FG="#E6EBF1", ENTRY="#242830", ENTRY_FG="#F2F5F9",
    CONSOLE_FG="#C9D0D8", OK_BG="#0E5C1B", OK_FG="#8CF3A2",
    WARN_BG="#8A5A00", WARN_FG="#FFD98A", ERR_BG="#5C2020", ERR_FG="#FF9C9C",
    CHIP="#1F242B", CHIP_FG="#9AA3AE", FOOT_HINT="#4A515B", TILE_FG="#FFFFFF",
    TILE_SUB="#E9EEF3", TILE_STATE="#F2F5F8",
)
LIGHT = dict(
    BG="#F2F4F7", PANEL="#FFFFFF", INK="#1B232C", INK_DIM="#4A5561",
    INK_MUTE="#7A8794", ACCENT="#0B78D0", LINE="#DCE2E9",
    BTN="#E4E9EF", BTN_FG="#26313D", ENTRY="#FFFFFF", ENTRY_FG="#1B232C",
    CONSOLE_FG="#33404E", OK_BG="#DFF3E4", OK_FG="#17662B",
    WARN_BG="#FFF0CE", WARN_FG="#8A5A00", ERR_BG="#FBE0E0", ERR_FG="#A32626",
    CHIP="#E4E9EF", CHIP_FG="#4A5561", FOOT_HINT="#9AA3AE", TILE_FG="#FFFFFF",
    TILE_SUB="#EAF0F6", TILE_STATE="#FFFFFF",
)
P = dict(DARK)  # 当前调色板（由主题切换更新）
FONT = "TkDefaultFont"
MONO = "TkFixedFont"


_PALETTES = {"dark": DARK, "light": LIGHT}

# 模块级颜色名（控件创建时读取，切主题会整体重建）
BG = DARK["BG"]
PANEL = DARK["PANEL"]
INK = DARK["INK"]
INK_DIM = DARK["INK_DIM"]
INK_MUTE = DARK["INK_MUTE"]
ACCENT = DARK["ACCENT"]
LINE = DARK["LINE"]
P = dict(DARK)


def apply_palette(name: str):
    """切换全局调色板，并同步模块级颜色名。"""
    global BG, PANEL, INK, INK_DIM, INK_MUTE, ACCENT, LINE, P, THEME_NAME
    P.clear()
    P.update(_PALETTES.get(name, DARK))
    BG, PANEL, INK = P["BG"], P["PANEL"], P["INK"]
    INK_DIM, INK_MUTE = P["INK_DIM"], P["INK_MUTE"]
    ACCENT, LINE = P["ACCENT"], P["LINE"]
    THEME_NAME = name if name in _PALETTES else "dark"


THEME_NAME = "dark"


def shade(hex_color: str, factor: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if factor >= 0:
        r = int(r + (255 - r) * factor)
        g = int(g + (255 - g) * factor)
        b = int(b + (255 - b) * factor)
    else:
        r, g, b = (int(c * (1 + factor)) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def pick_font() -> str:
    fams = set(tkfont.families())
    for cand in ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI",
                 "Noto Sans CJK SC", "Source Han Sans SC"):
        if cand in fams:
            return cand
    return "TkDefaultFont"


def mono_font() -> str:
    fams = set(tkfont.families())
    for cand in ("Cascadia Mono", "Consolas", "JetBrains Mono"):
        if cand in fams:
            return cand
    return "TkFixedFont"


class MetroButton(tk.Label):
    def __init__(self, master, text, command, bg=ACCENT, fg="#FFFFFF", **kw):
        super().__init__(master, text=text, bg=bg, fg=fg, font=(FONT, 10),
                         padx=16, pady=7, cursor="hand2", **kw)
        self._bg = bg
        self.command = command
        self.bind("<Enter>", lambda e: self.configure(bg=shade(self._bg, 0.12)))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<Button-1>", lambda e: self.command())

    def set_bg(self, bg):
        self._bg = bg
        self.configure(bg=bg)


class ContainerTile(tk.Frame):
    W, H = 214, 140

    def __init__(self, master, c: Container, index, on_select, on_run):
        super().__init__(master, bg=c.color, width=self.W, height=self.H,
                         highlightthickness=2, highlightbackground=c.color,
                         cursor="hand2")
        self.c = c
        self.index = index
        self.on_select = on_select
        self.on_run = on_run
        self.selected = False
        self.pack_propagate(False)

        mode = getattr(c, "engine_mode", MODE_AUTO) or MODE_AUTO
        mode_tag = {
            MODE_AUTO: "自动", MODE_SANDBOX: "沙盒", MODE_VM: "虚拟机",
            MODE_APP: "应用沙盒", MODE_PLAIN: "普通",
        }.get(mode, mode)
        last = getattr(c, "last_engine", "")
        engine_tag = f"→{'应用沙盒' if last == KIND_APP else '沙盒' if last == KIND_SANDBOX else '虚拟机' if last == KIND_VM else '普通'}" if last else ""
        self.name = tk.Label(self, text=c.name, bg=c.color, fg=INK,
                             font=(FONT, 14, "bold"), anchor="w")
        self.sub = tk.Label(self, text=f"{mode_tag}{engine_tag} · {c.target_name[:16]}",
                            bg=c.color, fg="#E9EEF3", font=(FONT, 9), anchor="w")
        self.state = tk.Label(self, text="○ 就绪", bg=c.color, fg="#F2F5F8",
                              font=(FONT, 9), anchor="w")
        self.name.place(x=14, y=14)
        self.sub.place(x=14, y=48)
        self.state.place(x=14, y=self.H - 32)

        for w in (self, self.name, self.sub, self.state):
            w.bind("<Button-1>", lambda e: self.on_select(self.index))
            w.bind("<Double-Button-1>", lambda e: self.on_run(self.index))
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

    def _hover_on(self, _e):
        if not self.selected:
            self._paint(shade(self.c.color, 0.10))

    def _hover_off(self, _e):
        if not self.selected:
            self._paint(self.c.color)

    def _paint(self, color):
        for w in (self, self.name, self.sub, self.state):
            w.configure(bg=color)
        self.configure(highlightbackground="#FFFFFF" if self.selected else color)

    def set_selected(self, flag: bool):
        self.selected = flag
        self._paint(self.c.color)

    def set_state(self, text: str, color: str = "#F2F5F8"):
        self.state.configure(text=text, fg=color)


class NewContainerDialog(tk.Toplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.title("新建容器")
        self.configure(bg=BG)
        self.geometry("560x560")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        global FONT
        pad = dict(padx=16, pady=6)
        tk.Label(self, text="新建隔离容器", bg=BG, fg=INK,
                 font=(FONT, 18, "bold")).pack(anchor="w", padx=20, pady=(18, 10))

        # 名称
        f1 = tk.Frame(self, bg=BG); f1.pack(fill="x", **pad)
        tk.Label(f1, text="名称", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.name_var = tk.StringVar(value="我的容器")
        tk.Entry(f1, textvariable=self.name_var, bg=P["ENTRY"], fg=P["ENTRY_FG"],
                 insertbackground=P["ENTRY_FG"], relief="flat", font=(FONT, 11),
                 bd=0).pack(side="left", fill="x", expand=True, ipady=7)

        # 类型
        f2 = tk.Frame(self, bg=BG); f2.pack(fill="x", **pad)
        tk.Label(f2, text="引擎", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.kind_var = tk.StringVar(value=KIND_SANDBOX)
        tk.Radiobutton(f2, text="沙盒（轻量·秒开）", variable=self.kind_var,
                       value=KIND_SANDBOX, bg=BG, fg=INK, selectcolor=P["ENTRY"],
                       font=(FONT, 10), activebackground=BG).pack(side="left")
        tk.Radiobutton(f2, text="虚拟机（支持驱动）", variable=self.kind_var,
                       value=KIND_VM, bg=BG, fg=INK, selectcolor=P["ENTRY"],
                       font=(FONT, 10), activebackground=BG).pack(side="left", padx=(12, 0))

        # 程序
        f3 = tk.Frame(self, bg=BG); f3.pack(fill="x", **pad)
        tk.Label(f3, text="程序", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.target_var = tk.StringVar()
        tk.Entry(f3, textvariable=self.target_var, bg=P["ENTRY"], fg=P["ENTRY_FG"],
                 insertbackground=P["ENTRY_FG"], relief="flat", font=(FONT, 10),
                 bd=0).pack(side="left", fill="x", expand=True, ipady=7)
        MetroButton(f3, "浏览…", self.browse, bg=P["BTN"], fg=P["BTN_FG"]).pack(
            side="left", padx=(8, 0))

        # 参数
        f4 = tk.Frame(self, bg=BG); f4.pack(fill="x", **pad)
        tk.Label(f4, text="参数", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.args_var = tk.StringVar()
        tk.Entry(f4, textvariable=self.args_var, bg=P["ENTRY"], fg=P["ENTRY_FG"],
                 insertbackground=P["ENTRY_FG"], relief="flat", font=(FONT, 10),
                 bd=0).pack(side="left", fill="x", expand=True, ipady=7)

        # 持久化
        f5 = tk.Frame(self, bg=BG); f5.pack(fill="x", **pad)
        tk.Label(f5, text="持久化", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.persist_var = tk.BooleanVar(value=True)
        tk.Checkbutton(f5, text="启用持久化虚拟磁盘（保存安装与配置）",
                       variable=self.persist_var, bg=BG, fg=INK,
                       selectcolor=P["ENTRY"], font=(FONT, 10),
                       activebackground=BG).pack(side="left")

        f6 = tk.Frame(self, bg=BG); f6.pack(fill="x", **pad)
        tk.Label(f6, text="磁盘大小", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.size_var = tk.StringVar(value="40")
        tk.Spinbox(f6, from_=10, to=200, textvariable=self.size_var, width=6,
                   bg=P["ENTRY"], fg=P["ENTRY_FG"], relief="flat", font=(FONT, 10),
                   bd=0).pack(side="left")

        # 引擎模式（四级降级）
        f7 = tk.Frame(self, bg=BG); f7.pack(fill="x", **pad)
        tk.Label(f7, text="引擎模式", bg=BG, fg=INK_DIM, font=(FONT, 10), width=10,
                 anchor="w").pack(side="left")
        self.mode_var = tk.StringVar(value=MODE_AUTO)
        modes = [
            (MODE_AUTO, "自动（沙盒→应用沙盒→普通，推荐）"),
            (MODE_SANDBOX, "Windows 沙盒（专业版）"),
            (MODE_APP, "应用沙盒 AppContainer（家庭版可用）"),
            (MODE_VM, "Hyper-V 虚拟机（支持驱动）"),
            (MODE_PLAIN, "普通进程（无隔离）"),
        ]
        import tkinter.ttk as ttk
        self.mode_combo = ttk.Combobox(f7, textvariable=self.mode_var, values=[m[0] for m in modes],
                                       state="readonly", width=30, font=(FONT, 9))
        self.mode_combo.pack(side="left", fill="x")
        self.mode_combo.current(0)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode)
        self.mode_hint = tk.Label(self, text="自动：优先用系统沙盒，没有则用内置应用沙盒，再兜底普通模式；家庭版可正常使用",
                                  bg=BG, fg=INK_MUTE, font=(FONT, 9), anchor="w")
        self.mode_hint.pack(anchor="w", padx=20, pady=(2, 0))

    def _on_mode(self, _e=None):
        hints = {
            MODE_AUTO: "自动：沙盒→应用沙盒→普通；家庭版可用，推荐",
            MODE_SANDBOX: "需要 Windows 专业版且已启用沙盒功能",
            MODE_APP: "家庭版可用；内核级低权限隔离，无需 Hyper-V/管理员",
            MODE_VM: "需要 Hyper-V；支持带内核驱动的程序",
            MODE_PLAIN: "无隔离，程序直接跑在宿主机，仅作最后兜底",
        }
        self.mode_hint.configure(text=hints.get(self.mode_var.get(), ""))

        tk.Label(self, text="提示：双击磁贴运行；带内核驱动的程序请选虚拟机引擎",
                 bg=BG, fg=INK_MUTE, font=(FONT, 9)).pack(anchor="w", padx=20, pady=(16, 0))

        btns = tk.Frame(self, bg=BG); btns.pack(fill="x", padx=20, pady=20)
        MetroButton(btns, "取消", self.destroy, bg=P["BTN"], fg=P["BTN_FG"]).pack(side="right")
        MetroButton(btns, "创建", self.ok, bg=ACCENT).pack(side="right", padx=(0, 8))

    def browse(self):
        p = filedialog.askopenfilename(
            title="选择要隔离运行的程序",
            filetypes=[("可执行程序", "*.exe *.msi *.msix *.appx *.msixbundle"),
                       ("所有文件", "*.*")],
        )
        if p:
            self.target_var.set(p)

    def ok(self):
        target = self.target_var.get().strip()
        if not target or not os.path.exists(target):
            messagebox.showwarning("程序不存在", "请选择有效的程序文件", parent=self)
            return
        self.result = dict(
            name=self.name_var.get().strip() or "未命名容器",
            kind=self.kind_var.get(),
            engine_mode=self.mode_var.get(),
            target=target,
            target_type=detect_target_type(target),
            args=self.args_var.get().strip(),
            persist=self.persist_var.get(),
            persist_gb=int(self.size_var.get() or 40),
        )
        self.destroy()


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} · Windows 应用隔离容器")
        self._set_icon()

        global FONT, MONO
        FONT = pick_font()
        MONO = mono_font()

        self.containers: list[Container] = load()
        self.ui_events: "Queue[tuple]" = Queue()
        self.selected = 0
        self.tiles: list[ContainerTile] = []
        self.env = {}
        apply_palette(self._load_theme())
        self._build()
        self._pump()
        self.root.after(200, self.check_env_async)

    # ---------------------------------------------------------- 主题 / 图标
    @staticmethod
    def _icon_path() -> str:
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, "app.ico")

    def _set_icon(self):
        p = self._icon_path()
        if os.path.exists(p):
            try:
                self.root.iconbitmap(p)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _theme_file() -> str:
        from core import BASE_DIR
        return os.path.join(BASE_DIR, "theme.txt")

    def _load_theme(self) -> str:
        try:
            with open(self._theme_file(), "r") as f:
                return f.read().strip()
        except Exception:  # noqa: BLE001
            return "dark"

    def _save_theme(self, name: str):
        try:
            with open(self._theme_file(), "w") as f:
                f.write(name)
        except Exception:  # noqa: BLE001
            pass

    def toggle_theme(self):
        nxt = "light" if THEME_NAME == "dark" else "dark"
        apply_palette(nxt)
        self._save_theme(nxt)
        # 重建整个界面
        for w in list(self.root.winfo_children()):
            w.destroy()
        self.root.configure(bg=BG)
        self.selected = min(self.selected, max(0, len(self.containers) - 1))
        self._build()
        self._write(f"已切换主题：{'清爽亮色' if nxt == 'light' else '经典深色'}", "ok")
        self.check_env_async()

    def _build(self):
        head = tk.Frame(self.root, bg=BG, height=74)
        head.pack(fill="x", padx=28, pady=(18, 0))
        head.pack_propagate(False)

        tb = tk.Frame(head, bg=BG); tb.pack(side="left")
        tk.Label(tb, text=APP_NAME, bg=BG, fg=INK,
                 font=(FONT, 24, "bold")).pack(anchor="w")
        tk.Label(tb, text="Windows 应用隔离容器 · 磁贴即入口", bg=BG, fg=INK_MUTE,
                 font=(FONT, 10)).pack(anchor="w")

        tools = tk.Frame(head, bg=BG); tools.pack(side="right", pady=8)
        self.env_label = tk.Label(tools, text="检测中…", bg=P["CHIP"], fg=P["CHIP_FG"],
                                  font=(FONT, 9, "bold"), padx=10, pady=4)
        self.env_label.pack(side="right", padx=(10, 0))
        self.admin_label = tk.Label(
            tools, text="ADMIN" if is_admin() else "USER",
            bg=P["OK_BG"] if is_admin() else P["CHIP"],
            fg=P["OK_FG"] if is_admin() else P["CHIP_FG"],
            font=(FONT, 9, "bold"), padx=10, pady=4)
        self.admin_label.pack(side="right", padx=(6, 0))
        MetroButton(tools, "☀/☾ 主题", self.toggle_theme, bg=P["BTN"],
                    fg=P["BTN_FG"]).pack(side="right")
        MetroButton(tools, "环境检查", self.check_env_async, bg=P["BTN"],
                    fg=P["BTN_FG"]).pack(side="right", padx=(8, 0))
        MetroButton(tools, "启用沙盒", self.enable_sandbox, bg=P["BTN"],
                    fg=P["BTN_FG"]).pack(side="right", padx=(8, 0))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=(16, 0))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2, minsize=420)
        body.rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self._build_tiles(left)
        self._build_actions(left)

        right = tk.Frame(body, bg=PANEL)
        right.grid(row=0, column=1, sticky="nsew", padx=(20, 0))
        self._build_console(right)

        foot = tk.Frame(self.root, bg=BG, height=26)
        foot.pack(fill="x", padx=28, pady=(6, 10))
        foot.pack_propagate(False)
        self.status = tk.Label(foot, text="就绪", bg=BG, fg=INK_MUTE,
                               font=(FONT, 9), anchor="w")
        self.status.pack(side="left")
        tk.Label(foot, text="双击磁贴 = 运行容器 · 单击 = 查看", bg=BG, fg=P["FOOT_HINT"],
                 font=(FONT, 9)).pack(side="right")

        self.root.bind("<Control-n>", lambda e: self.new_container())

    def _build_tiles(self, parent):
        wrap = tk.Frame(parent, bg=BG)
        wrap.grid(row=0, column=0, sticky="nsew")
        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)
        sb = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        sb.pack(side="right", fill="y")
        canvas.configure(yscrollcommand=sb.set)
        self.grid = tk.Frame(canvas, bg=BG)
        self.canvas = canvas
        canvas.create_window((0, 0), window=self.grid, anchor="nw")
        self.grid.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        self.render_tiles()

    def render_tiles(self):
        for t in self.tiles:
            t.destroy()
        self.tiles.clear()
        for i, c in enumerate(self.containers):
            t = ContainerTile(self.grid, c, i, self.select, self.run_container)
            t.grid(row=i // 3, column=i % 3, padx=(0, 10), pady=(0, 10), sticky="nw")
            self.tiles.append(t)
        if self.tiles and self.selected < len(self.tiles):
            self.tiles[self.selected].set_selected(True)

    def _build_actions(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        btn = dict(bg=P["BTN"], fg=P["BTN_FG"])
        MetroButton(bar, "+ 新建容器", self.new_container, bg=ACCENT).pack(side="left")
        MetroButton(bar, "运行", self.run_selected, **btn).pack(side="left", padx=(8, 0))
        MetroButton(bar, "回滚/重置", self.reset_container, **btn).pack(side="left", padx=(8, 0))
        MetroButton(bar, "打开磁盘", self.open_disk, **btn).pack(side="left", padx=(8, 0))
        MetroButton(bar, "导出", self.export_current, **btn).pack(side="left", padx=(8, 0))
        MetroButton(bar, "导入", self.import_new, **btn).pack(side="left", padx=(8, 0))
        MetroButton(bar, "删除", self.delete_container, **btn).pack(side="left", padx=(8, 0))
        tk.Label(parent, bg=BG, fg=P["INK_MUTE"], font=(FONT, 9), anchor="w",
                 text="Ctrl+N 新建 · 双击磁贴运行 · 回滚=VM还原快照/沙盒清空磁盘 · 导出分享整个环境"
                 ).grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_console(self, parent):
        head = tk.Frame(parent, bg=PANEL, height=44)
        head.pack(fill="x", padx=18, pady=(14, 0))
        head.pack_propagate(False)
        tk.Label(head, text="输出", bg=PANEL, fg=INK,
                 font=(FONT, 11, "bold")).pack(side="left")
        self.cur_label = tk.Label(head, text="当前：—", bg=PANEL, fg=INK_MUTE,
                                  font=(FONT, 9))
        self.cur_label.pack(side="left", padx=10)
        MetroButton(head, "清空", self.clear_console, bg=P["BTN"],
                    fg=P["BTN_FG"]).pack(side="right")

        tk.Frame(parent, bg=LINE, height=1).pack(fill="x", padx=18, pady=(10, 0))
        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=18, pady=(10, 14))
        self.text = tk.Text(
            wrap, bg=PANEL, fg=P["CONSOLE_FG"], relief="flat", bd=0,
            font=(MONO, 9), wrap="word", padx=10, pady=6,
            insertbackground=P["CONSOLE_FG"], cursor="arrow", width=1, height=1,
            highlightthickness=0, selectbackground=P["ACCENT"],
            selectforeground="#FFFFFF", spacing1=1, spacing3=2)
        self.text.pack(side="left", fill="both", expand=True)
        if THEME_NAME == "light":
            tags = (("cmd", "#0B6FA8"), ("out", "#33404E"), ("err", "#C0392B"),
                    ("ok", "#17662B"), ("warn", "#9A6B00"), ("dim", "#8894A1"),
                    ("time", "#AEB8C3"))
        else:
            tags = (("cmd", "#79D0FF"), ("out", "#C9D0D8"), ("err", "#FF7B72"),
                    ("ok", "#7CE38B"), ("warn", "#FFC857"), ("dim", "#69707B"),
                    ("time", "#3E4650"))
        for tag, color in tags:
            self.text.tag_configure(tag, foreground=color)
        self.text.configure(state="disabled")
        self._write(f"{APP_NAME} v{APP_VERSION} 就绪", "dim")
        self._write("新建容器 → 选程序 → 双击磁贴运行。沙盒引擎秒开，虚拟机引擎支持驱动。", "dim")

    # ---------------------------------------------------------- 日志
    def _write(self, msg: str, level="out"):
        self.text.configure(state="normal")
        self.text.insert("end", time.strftime("%H:%M:%S "), "time")
        self.text.insert("end", msg + "\n", level)
        self.text.see("end")
        if int(self.text.index("end-1c").split(".")[0]) > 4000:
            self.text.delete("1.0", "1000.0")
        self.text.configure(state="disabled")

    def clear_console(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def _pump(self):
        for level, msg in BUS.drain():
            self._write(msg, level)
        try:
            st = BUS.status.get_nowait()
            self.status.configure(text=st)
        except Exception:
            pass
        self.root.after(250, self._pump)

    # ---------------------------------------------------------- 环境
    def check_env_async(self):
        self.status.configure(text="检测隔离环境…")
        def worker():
            env = engine.probe_environment()
            self.ui_events.put(("env", env))
        threading.Thread(target=worker, daemon=True).start()

    def on_env(self, env: dict):
        self.env = env
        if env.get("sandbox_ready"):
            txt, bg, fg = "沙盒就绪", P["OK_BG"], P["OK_FG"]
        elif env.get("sandbox_feature"):
            txt, bg, fg = "沙盒待重启", P["WARN_BG"], P["WARN_FG"]
        else:
            txt, bg, fg = "沙盒未启用", P["ERR_BG"], P["ERR_FG"]
        self.env_label.configure(text=txt, bg=bg, fg=fg)
        self._write(
            "环境：Windows沙盒=%s / Hyper-V=%s / 应用沙盒=%s / 管理员=%s" %
            ("就绪" if env.get("sandbox_ready") else "无",
             "就绪" if env.get("vm_ready") else "无",
             "就绪" if env.get("appcontainer") else "无",
             "是" if env.get("admin") else "否"),
            "ok" if (env.get("sandbox_ready") or env.get("appcontainer")) else "warn")
        if not env.get("sandbox_ready") and env.get("appcontainer"):
            self._write("家庭版模式：Windows 沙盒/Hyper-V 不可用，已启用内置应用沙盒（AppContainer）", "warn")

    def enable_sandbox(self):
        if not is_admin():
            messagebox.showinfo("需要管理员", "请以管理员身份运行 WinCage，再点“启用沙盒”")
            return
        self.status.configure(text="启用 Windows 沙盒…")
        def worker():
            code, out = engine.enable_sandbox()
            self.ui_events.put(("msg", ("沙盒功能启用结果：" + out[-300:],
                                        "ok" if code == 0 else "err")))
            self.ui_events.put(("env", engine.probe_environment()))
        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------- 容器操作
    def select(self, i: int):
        if i >= len(self.tiles):
            return
        for t in self.tiles:
            t.set_selected(False)
        self.selected = i
        self.tiles[i].set_selected(True)
        c = self.containers[i]
        self.cur_label.configure(text=f"当前：{c.name}")

    def run_selected(self):
        if self.containers:
            self.run_container(self.selected)

    def run_container(self, i: int):
        if i >= len(self.containers):
            return
        c = self.containers[i]
        self.select(i)
        if not c.target or not os.path.exists(c.target):
            messagebox.showwarning("程序不存在", f"目标程序不存在：\n{c.target}")
            return
        self.status.configure(text=f"启动 {c.name}…")
        self.tiles[i].set_state("◐ 启动中…", "#FFC857")
        def worker():
            ok, msg = engine.start_container(c)
            self.ui_events.put(("run", (i, ok, msg)))
        threading.Thread(target=worker, daemon=True).start()

    def on_run(self, i: int, ok: bool, msg: str):
        c = self.containers[i]
        last = getattr(c, "last_engine", "")
        eng_name = {"sandbox": "Windows沙盒", "vm": "Hyper-V虚拟机",
                    "appcontainer": "应用沙盒", "plain": "普通进程"}.get(last, "")
        self._write(f"容器 {c.name}: {msg}" + (f"（引擎：{eng_name}）" if eng_name else ""),
                    "ok" if ok else "err")
        if i < len(self.tiles):
            self.tiles[i].set_state("● 已启动" if ok else "○ 启动失败",
                                    "#7CE38B" if ok else "#FF7B72")
        self.render_tiles()  # 刷新显示实际使用的引擎
        if i < len(self.tiles):
            self.tiles[i].set_selected(True)
        save(self.containers)

    def reset_container(self):
        """VM：还原到 CleanBase 快照；沙盒：清空持久化磁盘。"""
        if not self.containers:
            messagebox.showinfo("提示", "先创建一个容器")
            return
        c = self.containers[self.selected]
        if c.kind == KIND_VM:
            if not messagebox.askyesno("快照回滚",
                                       f"把「{c.name}」还原到 CleanBase 快照？\n当前状态会丢失。"):
                return
            msg = "虚拟机快照还原需要管理员权限，请以管理员运行"
            if is_admin():
                ok, msg = engine.VMEngine.restore(c)
            else:
                ok = False
            self._write(f"回滚 {c.name}: {msg}", "ok" if ok else "err")
        else:
            if not messagebox.askyesno("重置磁盘",
                                       f"清空「{c.name}」持久化磁盘的全部内容？\n安装的软件与配置都会消失。"):
                return
            ok, msg = engine.reset_sandbox_disk(c)
            self._write(f"重置 {c.name}: {msg}", "ok" if ok else "err")
            if not ok:
                messagebox.showwarning("重置失败", msg)

    def export_current(self):
        if not self.containers:
            messagebox.showinfo("提示", "先创建一个容器")
            return
        c = self.containers[self.selected]
        path = filedialog.asksaveasfilename(
            title="导出容器", defaultextension=".wincage",
            initialfile=f"{c.name}.wincage",
            filetypes=[("WinCage 容器", "*.wincage")])
        if not path:
            return
        self.status.configure(text=f"导出 {c.name}…")
        def worker():
            ok, msg = engine.export_container(c, path)
            self.ui_events.put(("msg", (f"导出 {c.name}: {msg}", "ok" if ok else "err")))
        threading.Thread(target=worker, daemon=True).start()

    def import_new(self):
        path = filedialog.askopenfilename(
            title="导入容器", filetypes=[("WinCage 容器", "*.wincage")])
        if not path:
            return
        self.status.configure(text="导入容器…")
        def worker():
            ok, msg, c = engine.import_container(path)
            self.ui_events.put(("import", (ok, msg, c)))
        threading.Thread(target=worker, daemon=True).start()

    def on_import(self, ok: bool, msg: str, c):
        if ok and c:
            self.containers.append(c)
            save(self.containers)
            self.render_tiles()
            self.selected = len(self.containers) - 1
            self.tiles[self.selected].set_selected(True)
        self._write(f"导入容器: {msg}", "ok" if ok else "err")
        if not ok:
            messagebox.showwarning("导入失败", msg)

    def open_disk(self):
        if not self.containers:
            messagebox.showinfo("提示", "先创建一个容器")
            return
        c = self.containers[self.selected]
        p = c.mount_dir if c.persist else c.disk_path
        if os.path.exists(p):
            open_path(p)
        else:
            messagebox.showinfo("磁盘未创建", "运行一次容器后，持久化磁盘才会创建")

    def new_container(self):
        dlg = NewContainerDialog(self.root, self)
        self.root.wait_window(dlg)
        if dlg.result:
            from config import new_container
            c = new_container(
                name=dlg.result["name"],
                target=dlg.result["target"],
                kind=dlg.result["kind"],
                engine_mode=dlg.result["engine_mode"],
                target_type=dlg.result["target_type"],
                args=dlg.result["args"],
                persist=dlg.result["persist"],
                persist_gb=dlg.result["persist_gb"],
                color=next_color(self.containers),
            )
            if c.kind == KIND_VM and not is_admin():
                messagebox.showinfo("提示", "虚拟机容器运行时需要管理员权限")
            self.containers.append(c)
            save(self.containers)
            self.render_tiles()
            self.selected = len(self.containers) - 1
            self.tiles[self.selected].set_selected(True)
            self.cur_label.configure(text=f"当前：{c.name}")
            self._write(f"已创建容器 {c.name}（{c.target_name}）", "ok")

    def delete_container(self):
        if not self.containers:
            return
        c = self.containers[self.selected]
        if not messagebox.askyesno("删除容器",
                                   f"删除容器「{c.name}」？\n（虚拟磁盘文件会保留在磁盘上）"):
            return
        self.containers.pop(self.selected)
        save(self.containers)
        self.selected = max(0, min(self.selected, len(self.containers) - 1))
        self.render_tiles()
        if self.tiles:
            self.tiles[self.selected].set_selected(True)

    def run(self):
        self.root.mainloop()


def launch():
    app = App()

    def dispatch():
        try:
            kind, payload = app.ui_events.get_nowait()
            if kind == "env":
                app.on_env(payload)
            elif kind == "msg":
                app._write(*payload)
            elif kind == "run":
                app.on_run(*payload)
            elif kind == "import":
                app.on_import(*payload)
        except Exception:
            pass
        app.root.after(100, dispatch)

    app.root.after(100, dispatch)
    app.run()
