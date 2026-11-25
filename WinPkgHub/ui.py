"""WinPkgHub - Windows 8 磁贴风格 UI（Tkinter，零第三方依赖）。"""
from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from queue import Empty, Queue

from core import BUS, IS_WIN, refresh_path
from managers import MANAGERS, is_admin

# ------------------------------------------------------------------ 主题
BG = "#16181C"          # 磁贴墙面
PANEL = "#101216"       # 控制台底
INK = "#FFFFFF"
INK_DIM = "#B7BEC7"
INK_MUTE = "#7A8290"
ACCENT = "#0B78D0"
LINE = "#262A31"

FONT = "TkDefaultFont"   # 启动后按系统字体替换
MONO = "TkFixedFont"


def shade(hex_color: str, factor: float) -> str:
    """factor > 0 变亮，< 0 变暗。"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
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
                 "Noto Sans CJK SC", "Source Han Sans SC", "WenQuanYi Micro Hei"):
        if cand in fams:
            return cand
    return "TkDefaultFont"


def mono_font() -> str:
    fams = set(tkfont.families())
    for cand in ("Cascadia Mono", "Consolas", "JetBrains Mono",
                 "DejaVu Sans Mono", "Liberation Mono"):
        if cand in fams:
            return cand
    return "TkFixedFont"


class MetroButton(tk.Label):
    """扁平按钮，无边框无圆角，hover 变色——磁贴时代的手感。"""

    def __init__(self, master, text, command, bg=ACCENT, fg="#FFFFFF", width=None, **kw):
        super().__init__(master, text=text, bg=bg, fg=fg, font=(FONT, 10),
                         padx=18, pady=8, cursor="hand2", **kw)
        if width:
            self.configure(width=width)
        self._bg = bg
        self.command = command
        self.bind("<Enter>", lambda e: self.configure(bg=shade(self._bg, 0.12)))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))
        self.bind("<Button-1>", lambda e: self.command())

    def set_bg(self, bg):
        self._bg = bg
        self.configure(bg=bg)


class Tile(tk.Frame):
    W, H = 214, 140

    def __init__(self, master, mgr, index, on_select, on_open):
        super().__init__(master, bg=mgr.color, width=self.W, height=self.H,
                         highlightthickness=2, highlightbackground=mgr.color,
                         cursor="hand2")
        self.mgr = mgr
        self.index = index
        self.on_select = on_select
        self.on_open = on_open
        self.pack_propagate(False)

        self.name = tk.Label(self, text=mgr.name, bg=mgr.color, fg=INK,
                             font=(FONT, 15, "bold"), anchor="w")
        self.sub = tk.Label(self, text=mgr.sub, bg=mgr.color, fg="#E9EEF3",
                            font=(FONT, 9), anchor="w")
        self.state = tk.Label(self, text="○ 检测中…", bg=mgr.color, fg="#F2F5F8",
                              font=(FONT, 9), anchor="w")

        self.name.place(x=14, y=14)
        self.sub.place(x=14, y=50)
        self.state.place(x=14, y=self.H - 34)

        for w in (self, self.name, self.sub, self.state):
            w.bind("<Button-1>", self._click)
            w.bind("<Double-Button-1>", lambda e: self.on_open(self.index))
            w.bind("<Enter>", self._hover_on)
            w.bind("<Leave>", self._hover_off)

    # --- 交互
    def _click(self, _e):
        self.on_select(self.index)

    def _hover_on(self, _e):
        if not self.selected:
            self._paint(shade(self.mgr.color, 0.10))

    def _hover_off(self, _e):
        if not self.selected:
            self._paint(self.mgr.color)

    def _paint(self, color):
        for w in (self, self.name, self.sub, self.state):
            w.configure(bg=color)
        self.configure(highlightbackground=color if not self.selected else "#FFFFFF")
        self._cur = color

    # --- 状态
    selected = False

    def set_selected(self, flag: bool):
        self.selected = flag
        if flag:
            self.configure(highlightbackground="#FFFFFF")
            self._paint(self.mgr.color)
        else:
            self.configure(highlightbackground=self.mgr.color)

    def set_state(self, installed: bool, version: str):
        if self.mgr.key == "ninite":
            self.state.configure(text="◻ 网页操作", fg="#F1F4F7")
            return
        if installed:
            ver = version.replace("v", "") if version else ""
            ver = ver.split()[0][:16] if ver else ""
            self.state.configure(text=f"● 已安装   {ver}", fg="#F2FFF2")
        else:
            self.state.configure(text="○ 未安装", fg="#F4F6F8")


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WinPkgHub · 多包管理器中枢")
        self.root.configure(bg=BG)
        self.root.geometry("1180x740")
        self.root.minsize(1080, 680)
        self._load_window_icon()

        global FONT, MONO
        FONT = pick_font()
        MONO = mono_font()

        self.ui_events: "Queue[tuple]" = Queue()
        self.selected = 0
        self.tiles: list[Tile] = []
        self._build()
        self._pump()
        self.root.bind("<Control-r>", lambda e: self.refresh_all())
        self.root.bind("<Control-R>", lambda e: self.refresh_all())
        self.root.after(300, self.refresh_all)

    def _load_window_icon(self):
        """加载 assets/icon.ico；图标缺失时不影响主程序启动。"""
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "assets", "icon.ico")
        if IS_WIN and os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except tk.TclError:
                pass
        else:
            png_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "assets", "icon.png")
            if os.path.exists(png_path):
                try:
                    photo = tk.PhotoImage(file=png_path)
                    self.root.iconphoto(True, photo)
                    self.root._icon_photo = photo
                except tk.TclError:
                    pass

    # ---------------------------------------------------------- 布局
    def _build(self):
        # 顶栏
        head = tk.Frame(self.root, bg=BG, height=74)
        head.pack(fill="x", padx=28, pady=(18, 0))
        head.pack_propagate(False)

        title_box = tk.Frame(head, bg=BG)
        title_box.pack(side="left")
        tk.Label(title_box, text="WinPkgHub", bg=BG, fg=INK,
                 font=(FONT, 24, "bold")).pack(anchor="w")
        tk.Label(title_box, text="九个包管理器 · 一个入口", bg=BG, fg=INK_MUTE,
                 font=(FONT, 10)).pack(anchor="w")

        tools = tk.Frame(head, bg=BG)
        tools.pack(side="right", pady=8)
        self.admin_label = tk.Label(
            tools,
            text="ADMIN" if is_admin() else "USER",
            bg="#1F242B" if not is_admin() else "#0E5C1B",
            fg="#9AA3AE" if not is_admin() else "#8CF3A2",
            font=(FONT, 9, "bold"), padx=10, pady=4,
        )
        self.admin_label.pack(side="right", padx=(10, 0))
        MetroButton(tools, "全部检测", self.refresh_all, bg="#232830", fg="#E6EBF1").pack(side="right")

        # 主体
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

        # 底栏
        foot = tk.Frame(self.root, bg=BG, height=26)
        foot.pack(fill="x", padx=28, pady=(6, 10))
        foot.pack_propagate(False)
        self.status = tk.Label(foot, text="就绪", bg=BG, fg=INK_MUTE, font=(FONT, 9), anchor="w")
        self.status.pack(side="left")
        tk.Label(foot, text="双击磁贴 = 直接安装该管理器", bg=BG, fg="#4A515B",
                 font=(FONT, 9)).pack(side="right")

    def _build_tiles(self, parent):
        grid = tk.Frame(parent, bg=BG)
        grid.grid(row=0, column=0, sticky="nw")
        for i, mgr in enumerate(MANAGERS):
            t = Tile(grid, mgr, i, self.select, self.install_manager)
            t.grid(row=i // 3, column=i % 3, padx=(0, 10), pady=(0, 10), sticky="nw")
            self.tiles.append(t)
        self.tiles[0].set_selected(True)

    def _build_actions(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        self.query = tk.Entry(
            bar, bg="#242830", fg="#F2F5F9", insertbackground="#F2F5F9",
            relief="flat", font=(FONT, 11), bd=0,
            highlightthickness=0, insertwidth=2,
        )
        self.query.pack(side="left", fill="x", expand=True, ipady=10)
        self.query.bind("<Return>", lambda e: self.do_search())
        self.placeholder = "输入包名，如 neovim / 7zip / ripgrep"
        self.query.insert(0, self.placeholder)
        self.query.configure(fg="#6E7681")
        self.query.bind("<FocusIn>", self._ph_off)
        self.query.bind("<FocusOut>", self._ph_on)

        MetroButton(bar, "搜索", self.do_search, bg="#252A32", fg="#E6EBF1").pack(side="left", padx=(10, 0))
        MetroButton(bar, "安装包", self.do_install_pkg).pack(side="left", padx=(8, 0))

        hint = tk.Label(
            parent, bg=BG, fg="#5C646F", font=(FONT, 9), anchor="w",
            text="输入包名后按 Enter 搜索；在已选磁贴对应的管理器里安装",
        )
        hint.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_console(self, parent):
        head = tk.Frame(parent, bg=PANEL, height=44)
        head.pack(fill="x", padx=18, pady=(14, 0))
        head.pack_propagate(False)
        tk.Label(head, text="输出", bg=PANEL, fg="#E6EBF1",
                 font=(FONT, 11, "bold")).pack(side="left")
        self.cur_mgr = tk.Label(head, text="当前：winget", bg=PANEL, fg=INK_MUTE, font=(FONT, 9))
        self.cur_mgr.pack(side="left", padx=10)
        MetroButton(head, "清空", self.clear_console, bg="#1B2027", fg="#98A1AC").pack(side="right")
        MetroButton(head, "刷新 PATH", self.do_refresh_path, bg="#1B2027", fg="#98A1AC").pack(
            side="right", padx=(0, 8))

        tk.Frame(parent, bg=LINE, height=1).pack(fill="x", padx=18, pady=(10, 0))

        wrap = tk.Frame(parent, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=18, pady=(10, 14))
        self.text = tk.Text(
            wrap, bg=PANEL, fg="#C9D0D8", relief="flat", bd=0,
            font=(MONO, 9), wrap="word", padx=10, pady=6,
            insertbackground=PANEL, cursor="arrow",
            width=1, height=1, highlightthickness=0,
            selectbackground="#243040", selectforeground="#FFFFFF",
            spacing1=1, spacing3=2,
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<MouseWheel>", self._on_wheel)
        self.text.bind("<Button-4>", lambda e: self.text.yview_scroll(-3, "units"))
        self.text.bind("<Button-5>", lambda e: self.text.yview_scroll(3, "units"))

        self.text.tag_configure("cmd", foreground="#79D0FF")
        self.text.tag_configure("out", foreground="#C9D0D8")
        self.text.tag_configure("err", foreground="#FF7B72")
        self.text.tag_configure("ok", foreground="#7CE38B")
        self.text.tag_configure("warn", foreground="#FFC857")
        self.text.tag_configure("dim", foreground="#69707B")
        self.text.tag_configure("time", foreground="#3E4650")
        self.text.configure(state="disabled")

        self.banner()

    # ---------------------------------------------------------- 控制台
    def banner(self):
        self._write("就绪 · Python %s · %s" %
                    (sys.version.split()[0], "Windows 11" if IS_WIN else "UI 预览"), "dim")
        self._write("未安装的管理器，点磁贴即自动部署。", "dim")

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

    def _ph_off(self, _e=None):
        if self.query.get() == self.placeholder:
            self.query.delete(0, "end")
            self.query.configure(fg="#F2F5F9")

    def _ph_on(self, _e=None):
        if not self.query.get().strip():
            self.query.insert(0, self.placeholder)
            self.query.configure(fg="#6E7681")

    def _q(self) -> str:
        v = self.query.get().strip()
        return "" if v == self.placeholder else v

    def _on_wheel(self, event):
        self.text.yview_scroll(-1 * (event.delta // 120 or 1), "units")

    def do_refresh_path(self):
        refresh_path()
        self.status.configure(text="PATH 已刷新")

    # ---------------------------------------------------------- 选择 / 安装
    def select(self, idx: int):
        self.tiles[self.selected].set_selected(False)
        self.selected = idx
        self.tiles[idx].set_selected(True)
        mgr = MANAGERS[idx]
        self.cur_mgr.configure(text=f"当前：{mgr.name}")
        self.status.configure(text=f"已选择 {mgr.name} — {mgr.hint}")

    @property
    def current(self):
        return MANAGERS[self.selected]

    def install_manager(self, idx=None):
        if idx is not None and idx != self.selected:
            self.select(idx)
        mgr = self.current
        if mgr.installed:
            self._write(f"{mgr.name} 已安装，无需重复操作", "ok")
            return
        self.status.configure(text=f"正在安装 {mgr.name}…")
        BUS.log(f"===== 安装 {mgr.name} =====", "cmd")
        mgr.install()

    def do_search(self):
        q = self._q()
        if not q:
            self.status.configure(text="请输入包名或关键字")
            return
        BUS.log(f"===== 在 {self.current.name} 中搜索：{q} =====", "cmd")
        self.current.search(q)

    def do_install_pkg(self):
        q = self._q()
        if not q:
            self.status.configure(text="请输入包名")
            return
        mgr = self.current
        if not mgr.installed and mgr.key not in ("ninite",):
            BUS.log(f"{mgr.name} 尚未安装，先自动安装管理器…", "warn")
            self.install_manager()
            self.status.configure(text="管理器安装完成后请再次点击『安装包』")
            return
        BUS.log(f"===== {mgr.name} 安装：{q} =====", "cmd")
        mgr.add(q)

    # ---------------------------------------------------------- 检测
    def refresh_all(self):
        self.status.configure(text="正在检测九个管理器…")

        def worker():
            for i, mgr in enumerate(MANAGERS):
                try:
                    ok, ver = mgr.probe()
                except Exception as e:  # noqa: BLE001
                    ok, ver = False, ""
                    BUS.log(f"{mgr.name} 检测异常：{e}", "warn")
                mgr.installed, mgr.version = ok, ver
                self.ui_events.put(("tile", i, ok, ver))
            self.ui_events.put(("done", sum(m.installed for m in MANAGERS)))

        threading.Thread(target=worker, daemon=True).start()

    # ---------------------------------------------------------- 事件泵
    def _pump(self):
        try:
            while True:
                level, msg = BUS.queue.get_nowait()
                self._write(msg, level)
        except Empty:
            pass
        try:
            while True:
                self.status.configure(text=BUS.status.get_nowait())
        except Empty:
            pass
        try:
            while True:
                ev = self.ui_events.get_nowait()
                if ev[0] == "tile":
                    _, i, ok, ver = ev
                    self.tiles[i].set_state(ok, ver)
                elif ev[0] == "done":
                    n = ev[1]
                    self.status.configure(text=f"检测完成：{n} / 9 已安装")
                    BUS.log(f"检测完成，已安装 {n} / 9", "ok")
        except Empty:
            pass
        self.root.after(60, self._pump)

    def run(self):
        self.root.mainloop()


def main():
    App().run()


if __name__ == "__main__":
    main()
