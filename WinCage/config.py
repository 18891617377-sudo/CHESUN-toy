"""WinCage - 容器配置模型与 JSON 持久化。"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional

from core import CONFIG_PATH

# 引擎类型
KIND_SANDBOX = "sandbox"   # Windows 沙盒：轻量、秒开、应用级
KIND_VM = "vm"             # Hyper-V 完整虚拟机：支持内核驱动
KIND_APP = "appcontainer"  # 自研 AppContainer 沙盒：家庭版可用（无沙盒/Hyper-V 时）
KIND_PLAIN = "plain"       # 普通进程兜底：无隔离，保证能跑

# 引擎选择模式
MODE_AUTO = "auto"    # 自动降级：沙盒 → VM → AppContainer → 普通
MODE_SANDBOX = "sandbox"
MODE_VM = "vm"
MODE_APP = "appcontainer"
MODE_PLAIN = "plain"

# 目标程序类型
TARGET_EXE = "exe"         # 绿色/portable 程序或安装器
TARGET_MSIX = "msix"       # MSIX 应用包
TARGET_INSTALLER = "installer"  # 安装器（写 Program Files + 注册表）

# 颜色（Win8 磁贴）
COLORS = ["#0B78D0", "#E85C26", "#1F9D55", "#8E44AD", "#C0392B", "#16A0A0", "#D68910"]


@dataclass
class Container:
    id: str
    name: str
    kind: str = KIND_SANDBOX
    engine_mode: str = MODE_AUTO  # auto=自动四级降级；或指定某一引擎
    target: str = ""            # 宿主机上的程序/安装包路径
    target_type: str = TARGET_EXE
    args: str = ""              # 附加启动参数
    persist: bool = True        # 是否启用持久化 VHDX
    persist_gb: int = 40        # 持久化磁盘大小
    network: bool = True
    memory_mb: int = 4096
    color: str = "#0B78D0"
    note: str = ""
    created: float = field(default_factory=time.time)
    disk_mounted: bool = False
    last_run: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Container":
        known = {f for f in Container.__dataclass_fields__}  # type: ignore[attr-defined]
        return Container(**{k: v for k, v in d.items() if k in known})

    @property
    def target_name(self) -> str:
        return os.path.basename(self.target) if self.target else "(未指定程序)"

    @property
    def disk_path(self) -> str:
        from core import DISKS_DIR
        return os.path.join(DISKS_DIR, f"{self.id}.vhdx")

    @property
    def mount_dir(self) -> str:
        from core import DISKS_DIR
        return os.path.join(DISKS_DIR, self.id)


def new_container(name: str, target: str, kind: str = KIND_SANDBOX,
                  target_type: str = TARGET_EXE, **kw) -> Container:
    return Container(
        id=uuid.uuid4().hex[:12],
        name=name or "未命名容器",
        kind=kind,
        target=target,
        target_type=target_type,
        **kw,
    )


def load() -> list[Container]:
    if not os.path.exists(CONFIG_PATH):
        return []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [Container.from_dict(d) for d in data]
    except Exception:
        pass
    return []


def save(containers: list[Container]):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in containers], f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)


def detect_target_type(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".msix" or ext == ".appx" or ext == ".msixbundle":
        return TARGET_MSIX
    name = os.path.basename(path).lower()
    if any(k in name for k in ("setup", "install", "installer", "msi")) or ext == ".msi":
        return TARGET_INSTALLER
    return TARGET_EXE


def next_color(containers: list[Container]) -> str:
    return COLORS[len(containers) % len(COLORS)]
