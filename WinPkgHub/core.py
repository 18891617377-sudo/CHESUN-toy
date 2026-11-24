"""WinPkgHub - 基础设施层：进程执行、日志总线、下载、PATH 刷新。"""
from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

APP_NAME = "WinPkgHub"
IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def _base_dir() -> str:
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


BASE_DIR = _base_dir()
TOOLS_DIR = os.path.join(BASE_DIR, "tools")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
for _d in (BASE_DIR, TOOLS_DIR, LOGS_DIR):
    os.makedirs(_d, exist_ok=True)


class Bus:
    """线程安全的日志 / 状态总线，UI 用 after() 轮询。"""

    def __init__(self):
        self.queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.status: "queue.Queue[str]" = queue.Queue()

    def log(self, msg: str, level: str = "info"):
        self.queue.put((level, str(msg)))

    def set_status(self, txt: str):
        self.status.put(txt)


BUS = Bus()


# ---------------------------------------------------------------- 进程执行
def resolve_cmd(cmd):
    """把裸命令名解析成完整路径。

    Windows 的 CreateProcess 只会自动补 .exe，不会补 .CMD/.BAT。
    scoop 这类以 .CMD shim 暴露的管理器，直接传 "scoop" 会报"命令不存在"，
    即使 shutil.which("scoop") 能找到 scoop.CMD。这里统一先解析一次。
    """
    if not IS_WIN or not cmd or isinstance(cmd, str):
        return cmd
    first = cmd[0]
    if not isinstance(first, str) or not first or os.path.dirname(first):
        return cmd  # 已经是绝对路径 / 相对路径，交给系统处理
    if os.path.splitext(first)[1]:
        return cmd  # 已带扩展名
    found = shutil.which(first)
    if not found:
        return cmd
    resolved = list(cmd)
    resolved[0] = found
    return resolved


def run_out(cmd, timeout: float = 25.0) -> tuple[int, str]:
    """静默执行并取回输出（用于探测版本）。"""
    try:
        p = subprocess.run(
            resolve_cmd(cmd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return p.returncode, (p.stdout or "").strip()
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def spawn(cmd, cwd=None, env=None) -> threading.Thread:
    """异步执行命令，逐行把输出推到 BUS。"""
    if isinstance(cmd, list):
        display = subprocess.list2cmdline(cmd) if IS_WIN else " ".join(cmd)
    else:
        display = cmd

    def worker():
        BUS.log("$ " + display, "cmd")
        try:
            p = subprocess.Popen(
                resolve_cmd(cmd),
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
            if p.stdout:
                for line in p.stdout:
                    line = line.rstrip()
                    if line:
                        BUS.log(line, "out")
            code = p.wait()
            BUS.log(f"[退出码 {code}]", "ok" if code == 0 else "err")
        except FileNotFoundError:
            BUS.log("命令不存在，请确认它已加入 PATH：" + display, "err")
        except Exception as e:  # noqa: BLE001
            BUS.log(f"执行失败：{e}", "err")
        finally:
            BUS.set_status("空闲")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def run_ps(script: str) -> threading.Thread:
    """执行一段 PowerShell 脚本。"""
    return spawn(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script]
    )


def run_elevated_ps(script: str, title: str = APP_NAME) -> threading.Thread:
    """UAC 提权执行脚本：写临时 ps1 → Start-Process -Verb RunAs → 跟随 transcript。"""

    def worker():
        ps1 = os.path.join(LOGS_DIR, f"elev_{int(time.time())}.ps1")
        log = os.path.join(LOGS_DIR, f"elev_{int(time.time())}.log")
        # 用自定义结束标记，不依赖 PowerShell 的本地化结束文案（中文/英文系统都适用）
        done = "__WPH_DONE__"
        inner = (
            f"$ErrorActionPreference='Continue'\n"
            f"Start-Transcript -Path '{log}' -Force | Out-Null\n"
            f"try {{\n{script}\n}} finally {{\n"
            f"  Write-Output '{done}'\n"
            f"  Stop-Transcript | Out-Null\n"
            f"}}\n"
        )
        with open(ps1, "w", encoding="utf-8-sig") as f:
            f.write(inner)

        BUS.log("需要管理员权限，正在请求 UAC 提权…", "warn")
        launcher = (
            f"Start-Process -FilePath powershell.exe -Verb RunAs "
            f'-ArgumentList @("-NoProfile","-ExecutionPolicy","Bypass","-File","{ps1}") '
            f"-WindowStyle Hidden"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", launcher],
                creationflags=CREATE_NO_WINDOW,
                timeout=600,
            )
        except Exception as e:  # noqa: BLE001
            BUS.log(f"提权失败：{e}", "err")
            BUS.set_status("空闲")
            return

        # 跟随日志文件
        deadline = time.time() + 900
        no_log_until = time.time() + 20  # 用户拒绝 UAC 时不会有日志，避免空等 15 分钟
        pos = 0
        finished = False
        while time.time() < deadline:
            if os.path.exists(log):
                with open(log, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(pos)
                    chunk = f.read()
                    pos = f.tell()
                for line in chunk.splitlines():
                    if line.strip():
                        BUS.log(line.rstrip(), "out")
                if (
                    done in chunk
                    or "Windows PowerShell 脚本结束" in chunk   # 中文系统
                    or "Windows PowerShell transcript end" in chunk  # 英文系统
                ):
                    finished = True
                    break
            elif time.time() > no_log_until:
                BUS.log("未检测到提权进程输出，可能已取消 UAC 或提权被拦截", "warn")
                break
            time.sleep(0.6)
        BUS.log("[提权任务结束]" if finished else "[提权任务中止]", "ok" if finished else "warn")
        BUS.set_status("空闲")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------- 下载
def download(url: str, dest: str, label: str = "") -> str:
    """带进度输出的下载。"""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    BUS.log(f"下载 {label or os.path.basename(dest)} ← {url}", "cmd")
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=30) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        last = 0
        while True:
            buf = r.read(64 * 1024)
            if not buf:
                break
            f.write(buf)
            got += len(buf)
            if total and time.time() - last > 0.5:
                BUS.log(f"  {got/1048576:.1f} / {total/1048576:.1f} MB", "dim")
                last = time.time()
    os.replace(tmp, dest)
    BUS.log(f"下载完成：{dest}", "ok")
    return dest


def github_asset(repo: str, pattern) -> str:
    """取 GitHub 最新 release 里匹配的资产地址。"""
    import json

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": APP_NAME},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    for a in data.get("assets", []):
        if pattern(a["name"]):
            return a["browser_download_url"]
    raise RuntimeError(f"{repo} 没有匹配的资产")


# ---------------------------------------------------------------- 环境
def find_msys2_root() -> str | None:
    for cand in (
        os.environ.get("MSYS2_ROOT"),
        r"C:\msys64",
        os.path.join(TOOLS_DIR, "msys64"),
    ):
        if cand and os.path.exists(os.path.join(cand, "usr", "bin", "bash.exe")):
            return cand
    return None


def find_cygwin_root() -> str | None:
    for cand in ("C:\\cygwin64", os.path.join(TOOLS_DIR, "cygwin64")):
        if os.path.exists(os.path.join(cand, "bin", "bash.exe")):
            return cand
    return None


def refresh_path():
    """把各管理器目录并入当前进程 PATH（安装完立即可用）。"""
    if not IS_WIN:
        return
    parts = [os.environ.get("PATH", "")]
    extra = [
        os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "shims"),
        os.path.join(os.environ.get("USERPROFILE", ""), "scoop", "apps"),
        r"C:\ProgramData\chocolatey\bin",
        os.path.join(TOOLS_DIR, "nuget"),
        os.path.join(TOOLS_DIR, "vcpkg"),
    ]
    m = find_msys2_root()
    if m:
        extra.append(os.path.join(m, "usr", "bin"))
    c = find_cygwin_root()
    if c:
        extra.append(os.path.join(c, "bin"))

    try:
        for scope in ("Machine", "User"):
            code, out = run_out(
                ["powershell", "-NoProfile", "-Command",
                 f"[Environment]::GetEnvironmentVariable('Path','{scope}')"], 15
            )
            if code == 0 and out:
                parts.append(out)
    except Exception:  # noqa: BLE001
        pass

    seen, merged = set(), []
    for chunk in parts + [os.pathsep.join(extra)]:
        for p in chunk.split(os.pathsep):
            k = p.strip().rstrip("\\").lower()
            if k and k not in seen:
                seen.add(k)
                merged.append(p)
    os.environ["PATH"] = os.pathsep.join(merged)
    BUS.log("PATH 已刷新（%d 项）" % len(merged), "ok")
