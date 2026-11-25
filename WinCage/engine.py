"""WinCage - 隔离引擎层。

SandboxEngine: Windows 沙盒 + 持久化 VHDX（轻量应用容器，秒开）
VMEngine:      Hyper-V 完整虚拟机（支持内核驱动的重量级应用）

两者都不需要第三方驱动、不需要改 WDAC，便于开源分发。
"""
from __future__ import annotations

import os
import subprocess
import time
from typing import Optional

from core import BUS, DISKS_DIR, IS_WIN, LOGS_DIR, CREATE_NO_WINDOW, human_size, run_out, run_ps
from config import (
    Container, KIND_SANDBOX, KIND_VM, KIND_APP, KIND_PLAIN,
    MODE_AUTO, MODE_SANDBOX, MODE_VM, MODE_APP, MODE_PLAIN,
    TARGET_EXE, TARGET_MSIX, TARGET_INSTALLER,
)
import engine_native

SANDBOX_DIST = r"C:\Windows\System32\WindowsSandbox.exe"
SB_USER = "WDAGUtilityAccount"
SB_DISK = r"C:\Users\WDAGUtilityAccount\Desktop\WinCageDisk"


# ---------------------------------------------------------------- 工具
def _write(path: str, lines: list[str], ascii_only: bool = True):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="ascii" if ascii_only else "utf-8-sig", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")


def _diskpart(script_path: str, timeout: int = 120) -> tuple[int, str]:
    return run_out(["diskpart", "/s", script_path], timeout)


def _is_feature_enabled(name: str) -> bool:
    code, out = run_ps(
        f"(Get-WindowsOptionalFeature -Online -FeatureName {name} -EA SilentlyContinue).State 2>$null"
    )
    # 无提权时 DISM 会报"需要提升"，此时用注册表/二进制做后备判断
    if "Enabled" in out:
        return True
    if "提升" in out or "elevation" in out.lower() or "740" in out:
        # 无提权后备：读 CBS 包状态注册表
        c, reg = run_ps(
            "Get-ChildItem 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component "
            "Based Servicing\\Packages' -EA SilentlyContinue | "
            "Where-Object {$_.PSChildName -match 'Sandbox|DisposableClientVM'} | "
            "Select-Object -First 1 -ExpandProperty PSChildName"
        )
        return bool(reg.strip())
    return False


def probe_environment() -> dict:
    """探测隔离能力，供 GUI 启动检查。"""
    sandbox_exe = os.path.exists(SANDBOX_DIST)
    sandbox_feature = _is_feature_enabled("Containers-DisposableClientVM")
    hv_module = "True" in run_ps(
        "[bool](Get-Module -ListAvailable Hyper-V)"
    )[1]
    hvms = "Running" in run_ps("(Get-Service vmms -EA SilentlyContinue).Status")[1]
    hypervisor = "True" in run_ps(
        "(Get-CimInstance Win32_ComputerSystem).HypervisorPresent"
    )[1]
    appcontainer = engine_native.available()
    return {
        "sandbox_binary": sandbox_exe,
        "sandbox_feature": sandbox_feature,
        "sandbox_ready": sandbox_exe and sandbox_feature,
        "hyperv_module": hv_module,
        "hyperv_service": hvms,
        "hypervisor": hypervisor,
        "vm_ready": hv_module and hvms and hypervisor,
        "appcontainer": appcontainer,
        "admin": __import__("core").is_admin(),
    }


def enable_sandbox() -> tuple[int, str]:
    """启用 Windows 沙盒功能（需管理员）。"""
    return run_ps(
        "Enable-WindowsOptionalFeature -Online "
        "-FeatureName Containers-DisposableClientVM -All -NoRestart | Out-String",
        180,
    )


def enable_hyperv() -> tuple[int, str]:
    """启用 Hyper-V（需管理员，需重启）。"""
    return run_ps(
        "Enable-WindowsOptionalFeature -Online -FeatureName Hyper-V -All -NoRestart | Out-String",
        300,
    )


# ---------------------------------------------------------------- VHDX 管理
def ensure_disk(c: Container) -> tuple[bool, str]:
    """确保持久化 VHDX 存在并挂载到 c.mount_dir。"""
    if not c.persist:
        return True, "未启用持久化"
    if not IS_WIN:
        return False, "仅 Windows 支持"

    disk = c.disk_path
    mount = c.mount_dir
    os.makedirs(mount, exist_ok=True)

    if not os.path.exists(disk):
        BUS.log(f"创建持久化磁盘 {os.path.basename(disk)} ({c.persist_gb}GB 动态)", "cmd")
        script = [
            f'create vdisk file="{disk}" maximum={c.persist_gb * 1024} type=expandable',
            f'select vdisk file="{disk}"',
            "attach vdisk",
            "create partition primary",
            "format fs=ntfs quick label=WinCage",
            f'assign mount="{mount}"',
            "exit",
        ]
        sp = os.path.join(LOGS_DIR, f"disk_create_{c.id}.txt")
        _write(sp, script)
        code, out = _diskpart(sp)
        if code != 0:
            return False, f"创建磁盘失败: {out[-300:]}"
        BUS.log("磁盘创建完成", "ok")
    else:
        # 已存在：若未挂载则挂载
        letter = _mounted_letter(disk)
        if not letter:
            script = [
                f'select vdisk file="{disk}"',
                "attach vdisk",
                f'assign mount="{mount}"',
                "exit",
            ]
            sp = os.path.join(LOGS_DIR, f"disk_mount_{c.id}.txt")
            _write(sp, script)
            code, out = _diskpart(sp)
            if code != 0:
                return False, f"挂载磁盘失败: {out[-300:]}"
            BUS.log("磁盘已挂载", "ok")

    # 建标准目录
    for sub in ("Apps", "Share", "Config", "Config\\Roaming", "Config\\Local"):
        p = os.path.join(mount, sub)
        if not os.path.exists(p):
            os.makedirs(p, exist_ok=True)
    return True, "磁盘就绪"


def _mounted_letter(disk: str) -> str:
    code, out = run_ps(
        f'(Get-VirtualDisk -EA SilentlyContinue | Where-Object {{$_.Path -eq "{disk}"}}).FriendlyName',
        20,
    )
    return out.strip() if code == 0 else ""


def detach_disk(c: Container) -> tuple[int, str]:
    if not IS_WIN or not c.persist or not os.path.exists(c.disk_path):
        return 0, "无需卸载"
    script = [
        f'select vdisk file="{c.disk_path}"',
        "detach vdisk",
        "exit",
    ]
    sp = os.path.join(LOGS_DIR, f"disk_detach_{c.id}.txt")
    _write(sp, script)
    return _diskpart(sp)


# ---------------------------------------------------------------- 沙盒引擎
class SandboxEngine:
    """Windows 沙盒 + 持久化 VHDX 的应用级容器。"""

    name = "沙盒容器"
    kind = KIND_SANDBOX

    @staticmethod
    def build_boot_script(c: Container) -> list[str]:
        """沙盒登录后自动执行：设置 PATH、重定向 AppData、启动目标程序。"""
        lines = [
            "@echo off",
            f'set "DISK={SB_DISK}"',
            'set "PATH=%DISK%\\Apps;%PATH%"',
            'if exist "%DISK%\\Apps\\*.lnk" copy /Y "%DISK%\\Apps\\*.lnk" "%USERPROFILE%\\Desktop\\" >nul 2>&1',
            "echo.",
            "echo  ============================================================",
            "echo   WinCage sandbox - isolated application container",
            "echo   Persistent disk: %DISK%",
            "echo  ============================================================",
            "echo.",
        ]

        if c.persist:
            lines += [
                "rem --- redirect AppData to persistent disk ---",
                'if exist "%DISK%\\Config\\.ready" goto :target',
                'xcopy /E /I /Y /H "%APPDATA%\\*" "%DISK%\\Config\\Roaming\\" >nul 2>&1',
                'xcopy /E /I /Y /H "%LOCALAPPDATA%\\*" "%DISK%\\Config\\Local\\" >nul 2>&1',
                'echo ready > "%DISK%\\Config\\.ready"',
                ":target",
            ]

        lines += ["rem --- launch target ---"]
        target_name = os.path.basename(c.target) if c.target else ""
        sandbox_target = f"{SB_DISK}\\{target_name}"

        if c.target_type == TARGET_MSIX:
            lines += [
                f'if exist "{sandbox_target}" (',
                f'  powershell -NoProfile -Command "Add-AppxPackage \'{sandbox_target}\'"',
                ") else (",
                f'  echo MSIX not found: {sandbox_target}',
                ")",
            ]
        else:
            cmdline = f'"{sandbox_target}" {c.args}'.strip()
            lines += [
                f'if exist "{sandbox_target}" (',
                f'  start "" {cmdline}',
                ") else (",
                f'  echo Target not found: {sandbox_target}',
                f'  echo Put {target_name} into the WinCageDisk folder.',
                ")",
            ]
        lines += ["echo."]
        return lines

    @staticmethod
    def build_wsb(c: Container, boot_path: str) -> str:
        """生成 .wsb 配置 XML。"""
        mem = max(2048, c.memory_mb)
        net = "Enable" if c.network else "Disable"
        mapped = ""
        if c.persist:
            mapped = (
                "  <MappedFolders>\n"
                f"    <MappedFolder><HostFolder>{c.mount_dir}</HostFolder>"
                f"<SandboxFolder>{SB_DISK}</SandboxFolder>"
                "<ReadOnly>false</ReadOnly></MappedFolder>\n"
                "  </MappedFolders>\n"
            )
        return (
            "<Configuration>\n"
            "  <VGpu>Enable</VGpu>\n"
            f"  <Networking>{net}</Networking>\n"
            f"  <MemoryInMB>{mem}</MemoryInMB>\n"
            + mapped +
            "  <LogonCommand>\n"
            f"    <Command>{boot_path}</Command>\n"
            "  </LogonCommand>\n"
            "</Configuration>\n"
        )

    @staticmethod
    def prepare(c: Container) -> tuple[bool, str, Optional[str]]:
        """准备运行环境：磁盘 + 目标程序拷贝到磁盘 + 生成 boot/wsb。返回 (ok, msg, wsb_path)。"""
        ok, msg = ensure_disk(c)
        if not ok:
            return False, msg, None

        # 把目标程序拷进持久盘（这样每次沙盒启动都能找到）
        if c.target and os.path.exists(c.target):
            name = os.path.basename(c.target)
            dest = os.path.join(c.mount_dir, name)
            if not os.path.exists(dest):
                try:
                    BUS.log(f"拷贝目标程序到持久盘: {name}", "cmd")
                    import shutil
                    shutil.copy2(c.target, dest)
                except Exception as e:  # noqa: BLE001
                    return False, f"拷贝目标程序失败: {e}", None

        # boot.cmd 放在持久盘（沙盒内可见）
        boot_path = os.path.join(c.mount_dir, "boot.cmd")
        _write(boot_path, SandboxEngine.build_boot_script(c))

        # wsb 放日志目录（宿主机）
        wsb_path = os.path.join(LOGS_DIR, f"wincage_{c.id}.wsb")
        sandbox_boot = f"{SB_DISK}\\boot.cmd"
        wsb = SandboxEngine.build_wsb(c, sandbox_boot)
        with open(wsb_path, "w", encoding="ascii", newline="\r\n") as f:
            f.write(wsb)

        return True, "环境就绪", wsb_path

    @staticmethod
    def start(c: Container) -> tuple[bool, str]:
        ok, msg, wsb = SandboxEngine.prepare(c)
        if not ok:
            return False, msg
        if not os.path.exists(SANDBOX_DIST):
            return False, "Windows 沙盒未启用（请先在界面点“启用沙盒”并重启）"
        BUS.log(f"启动沙盒容器: {c.name}", "cmd")
        try:
            subprocess.Popen(
                [SANDBOX_DIST, wsb],
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as e:  # noqa: BLE001
            return False, f"启动失败: {e}"
        c.last_run = time.time()
        c.disk_mounted = c.persist
        return True, "沙盒已启动"


# ---------------------------------------------------------------- VM 引擎
class VMEngine:
    """Hyper-V 完整虚拟机（支持内核驱动应用）。"""

    name = "虚拟机容器"
    kind = KIND_VM

    @staticmethod
    def build_create_script(c: Container, iso: str) -> str:
        mem_min = max(2048, c.memory_mb // 2)
        mem_max = max(mem_min, c.memory_mb * 2)
        vhd = c.disk_path
        return f"""
$ErrorActionPreference='Stop'
$vmName = 'WinCage-{c.id}'
if (Get-VM -Name $vmName -EA SilentlyContinue) {{ Write-Output 'VM_EXISTS'; exit 0 }}
New-VM -Name $vmName -Generation 2 -MemoryStartupBytes {mem_min}MB `
  -SwitchName 'Default Switch' -Path '{DISKS_DIR}' | Out-Null
Set-VMMemory -VMName $vmName -DynamicMemoryEnabled $true `
  -MinimumBytes {mem_min}MB -MaximumBytes {mem_max}MB | Out-Null
Set-VMProcessor -VMName $vmName -Count 4 | Out-Null
New-VHD -Path '{vhd}' -SizeBytes {c.persist_gb}GB -Dynamic | Out-Null
Add-VMHardDiskDrive -VMName $vmName -Path '{vhd}' | Out-Null
if ('{iso}' -and (Test-Path '{iso}')) {{
  Add-VMDvdDrive -VMName $vmName -Path '{iso}' | Out-Null
  Set-VMFirmware -VMName $vmName -FirstBootDevice (Get-VMDvdDrive -VMName $vmName) | Out-Null
}}
Enable-VMTPM -VMName $vmName -EA SilentlyContinue | Out-Null
Set-VMFirmware -VMName $vmName -EnableSecureBoot On -EA SilentlyContinue | Out-Null
Checkpoint-VM -Name $vmName -SnapshotName 'CleanBase' | Out-Null
Write-Output 'VM_CREATED'
""".strip()

    @staticmethod
    def find_iso() -> Optional[str]:
        """找现成的 Windows ISO。"""
        import glob
        for pat in ("D:\\*.iso", "E:\\*.iso", "C:\\Users\\*\\Downloads\\*.iso"):
            hits = glob.glob(pat)
            if hits:
                return hits[0]
        return None

    @staticmethod
    def create(c: Container) -> tuple[bool, str]:
        if not __import__("core").is_admin():
            return False, "创建虚拟机需要管理员权限（请以管理员身份运行）"
        iso = VMEngine.find_iso()
        script = VMEngine.build_create_script(c, iso or "")
        sp = os.path.join(LOGS_DIR, f"vm_create_{c.id}.ps1")
        _write(sp, script.splitlines())
        code, out = run_ps(f"& '{sp}'", 300)
        if "VM_CREATED" in out or "VM_EXISTS" in out:
            return True, "虚拟机已创建"
        return False, f"创建失败: {out[-400:]}"

    @staticmethod
    def start(c: Container) -> tuple[bool, str]:
        vm = f"WinCage-{c.id}"
        code, out = run_ps(
            f"$v=Get-VM -Name '{vm}' -EA SilentlyContinue; "
            f"if(-not $v){{'NO_VM'}} else {{Start-VM -Name '{vm}' -EA SilentlyContinue; 'STARTED'}}",
            60,
        )
        if "STARTED" in out:
            c.last_run = time.time()
            return True, "虚拟机已启动"
        if "NO_VM" in out:
            return VMEngine.create(c)
        return False, f"启动失败: {out[-300:]}"

    @staticmethod
    def checkpoint(c: Container, name: str = "Snapshot") -> tuple[bool, str]:
        vm = f"WinCage-{c.id}"
        code, out = run_ps(f"Checkpoint-VM -Name '{vm}' -SnapshotName '{name}' -EA Stop; 'OK'", 120)
        return ("OK" in out), out[-300:]

    @staticmethod
    def restore(c: Container, checkpoint_name: str = "CleanBase") -> tuple[bool, str]:
        vm = f"WinCage-{c.id}"
        code, out = run_ps(
            f"Restore-VMSnapshot -Name '{checkpoint_name}' -VMName '{vm}' -Confirm:$false -EA Stop; 'OK'",
            180,
        )
        return ("OK" in out), out[-300:]


# ---------------------------------------------------------------- 普通进程兜底
class PlainEngine:
    """最后兜底：普通进程，无隔离，保证程序在任何机器上都能启动。"""
    name = "普通进程（无隔离）"
    kind = KIND_PLAIN

    @staticmethod
    def start(c: Container) -> tuple[bool, str]:
        import subprocess
        if not c.target or not os.path.exists(c.target):
            return False, "程序不存在"
        try:
            subprocess.Popen([c.target] + (c.args.split() if c.args else []),
                             cwd=os.path.dirname(c.target))
            BUS.log("警告：普通模式无隔离，程序直接运行在宿主机", "warn")
            return True, "已在普通模式启动（无隔离）"
        except Exception as e:  # noqa: BLE001
            return False, f"启动失败: {e}"


# ---------------------------------------------------------------- 分发器（四级降级）
ENGINES = {
    KIND_SANDBOX: SandboxEngine,
    KIND_VM: VMEngine,
    KIND_APP: engine_native.AppContainerEngine,
    KIND_PLAIN: PlainEngine,
}

MODE_TO_KIND = {
    MODE_SANDBOX: KIND_SANDBOX,
    MODE_VM: KIND_VM,
    MODE_APP: KIND_APP,
    MODE_PLAIN: KIND_PLAIN,
}


def choose_engine(c: Container) -> str:
    """按 engine_mode 选择实际引擎；auto 时按能力四级降级。"""
    mode = getattr(c, "engine_mode", MODE_AUTO) or MODE_AUTO
    if mode in MODE_TO_KIND:
        return MODE_TO_KIND[mode]
    if mode != MODE_AUTO:
        return MODE_PLAIN

    env = probe_environment()
    # 带内核驱动的虚拟机容器，优先 VM；否则普通程序优先轻量沙盒
    if c.kind == KIND_VM:
        if env["vm_ready"]:
            return KIND_VM
        # 无 Hyper-V（家庭版）：AppContainer 也跑不了驱动类，降级到普通并提示
        return KIND_PLAIN
    # 普通程序：沙盒 → AppContainer → 普通
    if env["sandbox_ready"]:
        return KIND_SANDBOX
    if env["appcontainer"]:
        return KIND_APP
    return KIND_PLAIN


def start_container(c: Container) -> tuple[bool, str]:
    kind = choose_engine(c)
    eng = ENGINES.get(kind)
    if not eng:
        return False, f"未知引擎: {kind}"
    BUS.log(f"引擎选择: {eng.name}（模式={getattr(c, 'engine_mode', MODE_AUTO)}）", "cmd")
    if kind == KIND_PLAIN and getattr(c, "engine_mode", MODE_AUTO) == MODE_AUTO:
        BUS.log("本机无可用隔离引擎，已降级为普通模式", "warn")
    c.last_engine = kind  # type: ignore[attr-defined]
    return eng.start(c)


# ---------------------------------------------------------------- 导入 / 导出
def export_container(c: Container, out_path: str) -> tuple[bool, str]:
    """把容器配置打包成 .wincage（JSON + 可选虚拟磁盘），便于分发。"""
    import json
    import zipfile

    try:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("container.json", json.dumps(c.to_dict(), ensure_ascii=False, indent=2))
            if c.persist and os.path.exists(c.disk_path):
                BUS.log("打包虚拟磁盘（可能较大）…", "cmd")
                z.write(c.disk_path, "disk.vhdx")
        size = os.path.getsize(out_path)
        return True, f"已导出 {human_size(size)}"
    except Exception as e:  # noqa: BLE001
        return False, f"导出失败: {e}"


def import_container(in_path: str) -> tuple[bool, str, Optional["Container"]]:
    """从 .wincage 导入容器。返回 (ok, msg, container)。"""
    import json
    import shutil
    import zipfile

    from config import Container as C

    try:
        with zipfile.ZipFile(in_path, "r") as z:
            data = json.loads(z.read("container.json").decode("utf-8"))
            c = C.from_dict(data)
            # 重新生成 ID，避免和已有容器冲突
            import uuid
            c.id = uuid.uuid4().hex[:12]
            if "disk.vhdx" in z.namelist() and c.persist:
                os.makedirs(DISKS_DIR, exist_ok=True)
                with z.open("disk.vhdx") as src, open(c.disk_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return True, "导入成功", c
    except Exception as e:  # noqa: BLE001
        return False, f"导入失败: {e}", None


def reset_sandbox_disk(c: Container) -> tuple[bool, str]:
    """沙盒容器：重置持久化磁盘到空白状态（保留磁盘文件，删内容）。"""
    import shutil
    if c.kind != KIND_SANDBOX or not c.persist:
        return False, "仅沙盒容器可重置磁盘"
    if not os.path.exists(c.mount_dir):
        return True, "磁盘尚未创建，无需重置"
    try:
        for name in os.listdir(c.mount_dir):
            p = os.path.join(c.mount_dir, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
            else:
                os.remove(p)
        return True, "磁盘已清空（配置 / 安装全部归零）"
    except Exception as e:  # noqa: BLE001
        return False, f"重置失败: {e}"
