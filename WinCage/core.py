"""WinCage - 基础设施层：路径、进程执行、日志总线。零第三方依赖。"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import time

APP_NAME = "WinCage"
APP_VERSION = "0.1.0"
IS_WIN = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def _base_dir() -> str:
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME)


BASE_DIR = _base_dir()
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DISKS_DIR = os.path.join(BASE_DIR, "disks")
CONFIG_PATH = os.path.join(BASE_DIR, "containers.json")
for _d in (BASE_DIR, LOGS_DIR, DISKS_DIR):
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

    def drain(self, limit: int = 200) -> list[tuple[str, str]]:
        out = []
        while len(out) < limit:
            try:
                out.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return out


BUS = Bus()


def is_admin() -> bool:
    if not IS_WIN:
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def run_out(cmd, timeout: float = 30.0) -> tuple[int, str]:
    """静默执行并取回输出。"""
    try:
        p = subprocess.run(
            cmd,
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


def run_ps(script: str, timeout: float = 60.0) -> tuple[int, str]:
    """执行 PowerShell 脚本，返回 (code, output)。"""
    return run_out(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout,
    )


def spawn(cmd, cwd=None, env=None) -> threading.Thread:  # type: ignore[name-defined]
    """异步执行命令，逐行把输出推到 BUS。"""
    import threading

    display = subprocess.list2cmdline(cmd) if isinstance(cmd, list) else str(cmd)

    def worker():
        BUS.log("$ " + display, "cmd")
        try:
            p = subprocess.Popen(
                cmd,
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
            BUS.log("命令不存在：" + display, "err")
        except Exception as e:  # noqa: BLE001
            BUS.log(f"执行失败：{e}", "err")
        finally:
            BUS.set_status("空闲")

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return t


def open_path(path: str):
    """用系统默认方式打开文件或文件夹。"""
    if not IS_WIN:
        return
    os.startfile(path)  # type: ignore[attr-defined]


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PB"
