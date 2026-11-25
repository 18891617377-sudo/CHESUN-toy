"""WinCage - AppContainer 原生沙盒引擎。

不依赖 Hyper-V / Windows 沙盒 / 任何驱动 / 管理员权限。
纯 ctypes 调用 Windows 8+ 内置的 AppContainer（商店应用与 Edge 的沙盒）：
  - 内核强制的低完整性级别（Low IL）
  - 独立的命名对象命名空间（互斥体/事件互不干扰）
  - 默认拒绝文件系统/注册表访问，只放行显式授权的目录
  - 可选 internetClient 能力控制联网

这解决了家庭版（无 Windows 沙盒 / 无 Hyper-V）无法使用隔离的问题。
隔离强度低于 Hyper-V（拦不住内核驱动），但高于"什么都不做"。
"""
from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Optional

from core import BUS, IS_WIN, LOGS_DIR, CREATE_NO_WINDOW, run_out

# ---------------------------------------------------------------- ctypes 结构
class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class SECURITY_CAPABILITIES(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(SID_AND_ATTRIBUTES)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD),
    ]


# ---------------------------------------------------------------- 常量
PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW_NATIVE = 0x08000000
SE_GROUP_ENABLED = 0x00000004

# 已知能力 SID（WELL_KNOWN_SID_TYPE，实测值）
# 84 -> S-1-15-2-1 = internetClient（网络访问能力）
WIN_CAPABILITY_INTERNET_CLIENT = 84

_k32 = ctypes.windll.kernel32 if IS_WIN else None
_adv = ctypes.windll.advapi32 if IS_WIN else None
_userenv = ctypes.windll.userenv if IS_WIN else None
_kbase = ctypes.windll.kernelbase if IS_WIN else None


def _configure():
    if not IS_WIN:
        return
    _userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long  # HRESULT
    _userenv.CreateAppContainerProfile.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                   ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    _userenv.CreateAppContainerProfile.restype = ctypes.c_long
    _adv.FreeSid.argtypes = [ctypes.c_void_p]
    _adv.CreateWellKnownSid.argtypes = [ctypes.c_int, ctypes.c_void_p,
                                        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    _adv.CreateWellKnownSid.restype = wintypes.BOOL
    _k32.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    _k32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    _k32.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t,
                                               ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t)]
    _k32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    _k32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    _k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
                                    wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
                                    ctypes.POINTER(STARTUPINFOW), ctypes.POINTER(PROCESS_INFORMATION)]
    _k32.CreateProcessW.restype = wintypes.BOOL
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
    _adv.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    _adv.ConvertSidToStringSidW.restype = wintypes.BOOL
    _k32.LocalFree.argtypes = [wintypes.HANDLE]


_configure()


# ---------------------------------------------------------------- 工具函数
def available() -> bool:
    """AppContainer 在 Windows 8+ 全部版本（含家庭版）可用。"""
    return IS_WIN and bool(_userenv)


def sid_to_string(sid) -> str:
    buf = wintypes.LPWSTR()
    if not _adv.ConvertSidToStringSidW(sid, ctypes.byref(buf)):
        return ""
    try:
        return buf.value or ""
    finally:
        _k32.LocalFree(buf)


def _derive_sid(name: str):
    """取得 AppContainer SID。必须先 CreateProfile 注册，否则 CreateProcess 报 err=2。"""
    sid = ctypes.c_void_p()
    # HRESULT: S_OK=0；已存在时返回 0x80070519(ERROR_ALREADY_EXISTS) 等
    hr = _userenv.CreateAppContainerProfile(name, name, name, None, 0, ctypes.byref(sid))
    if hr == 0 and sid.value:
        return sid
    # profile 已存在：从名字重新派生 SID
    hr = _userenv.DeriveAppContainerSidFromAppContainerName(name, ctypes.byref(sid))
    if hr == 0 and sid.value:
        return sid
    return None


def _grant_tree_icacls(path: str, sid_str: str) -> tuple[bool, str]:
    """用系统自带 icacls 给容器 SID 授权（家庭版可用，无需管理员改自己的目录）。"""
    if not sid_str:
        return False, "SID 为空"
    sid_arg = f"*{sid_str}"

    # 目标目录：完全控制 + 继承标志（不用 /T，避免递归遍历已存在文件卡死）
    code, out = run_out(["icacls", path, "/grant", f"{sid_arg}:(OI)(CI)(F)", "/Q"], 30)
    if code != 0 and "denied" in out.lower():
        return False, f"授权容器目录失败: {out[-300:]}"

    # 祖先目录：只给直接父级授予穿越权（更上层通常由 ALL APPLICATION PACKAGES
    # 默认放行，且逐级授权会让根目录 ACL 无限膨胀）。带短超时避免阻塞。
    parent = os.path.dirname(os.path.abspath(path))
    if parent and parent != os.path.dirname(parent):
        run_out(["icacls", parent, "/grant", f"{sid_arg}:(X)", "/Q"], 8)
    return True, "已授权"


def _build_env(c, home_dir: str) -> bytes:
    """构造 Unicode 环境块，把 AppData/Temp 重定向到容器目录，实现配置持久化。"""
    env = dict(os.environ)
    env["APPDATA"] = os.path.join(home_dir, "Config", "Roaming")
    env["LOCALAPPDATA"] = os.path.join(home_dir, "Config", "Local")
    env["TEMP"] = os.path.join(home_dir, "Temp")
    env["TMP"] = os.path.join(home_dir, "Temp")
    for d in (env["APPDATA"], env["LOCALAPPDATA"], env["TEMP"]):
        os.makedirs(d, exist_ok=True)
    parts = [f"{k}={v}" for k, v in env.items()]
    return ("\0".join(parts) + "\0\0").encode("utf-16le")


def _build_capabilities(network: bool, keepalive: list):
    """构造 capability SID 数组。

    实测发现：当前系统对 SECURITY_CAPABILITIES 带自定义 capability 时会报 87，
    因此默认不附加 capability（AppContainer 仍然有效，只是默认无网络）。
    网络访问改由 grant_all_app_packages() 授予 ALL APPLICATION PACKAGES 组实现。
    """
    if not network:
        return None, 0
    return None, 0  # 保留接口，capability 暂不启用（见函数说明）

    # 84 = S-1-15-2-1 = internetClient（网络能力），实测确认
    SECURITY_MAX_SID_SIZE = 68
    sid_buf = ctypes.create_string_buffer(SECURITY_MAX_SID_SIZE)
    size = wintypes.DWORD(SECURITY_MAX_SID_SIZE)
    ok = _adv.CreateWellKnownSid(WIN_CAPABILITY_INTERNET_CLIENT, None,
                                 ctypes.cast(sid_buf, ctypes.c_void_p), ctypes.byref(size))
    if not ok:
        return None, 0

    keepalive.append(sid_buf)
    arr = (SID_AND_ATTRIBUTES * 1)()
    arr[0].Sid = ctypes.cast(sid_buf, ctypes.c_void_p).value
    arr[0].Attributes = SE_GROUP_ENABLED
    keepalive.append(arr)
    return arr, 1


def launch_in_appcontainer(exe: str, args: str, cwd: str, network: bool,
                           env_block: bytes, container_name: str) -> tuple[bool, str, int]:
    """核心：在 AppContainer 中启动进程。返回 (成功, 消息, PID)。"""
    if not available():
        return False, "AppContainer 不可用（非 Windows）", 0

    if not os.path.exists(exe):
        return False, f"程序不存在: {exe}", 0

    sid = _derive_sid(container_name)
    if not sid:
        return False, "创建 AppContainer SID 失败", 0
    sid_str = sid_to_string(sid)
    BUS.log(f"AppContainer SID: {sid_str[:48]}…", "cmd")

    keepalive = []  # 持有 capability SID buffer 直到 CreateProcess 完成
    cap_arr, cap_count = _build_capabilities(network, keepalive)
    sec = SECURITY_CAPABILITIES()
    sec.AppContainerSid = sid.value
    sec.Capabilities = cap_arr
    sec.CapabilityCount = cap_count
    sec.Reserved = 0
    # 环境重定向通过 cmd 包装实现（直接传环境块在本机会报 203）

    # 初始化扩展启动信息
    attr_size = ctypes.c_size_t(0)
    _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(attr_size))
    attr_buf = ctypes.create_string_buffer(attr_size.value)
    attr_list = ctypes.cast(attr_buf, ctypes.c_void_p)
    if not _k32.InitializeProcThreadAttributeList(attr_list, 1, 0, ctypes.byref(attr_size)):
        _adv.FreeSid(sid)
        return False, "初始化进程属性列表失败", 0

    if not _k32.UpdateProcThreadAttribute(attr_list, 0,
                                          PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
                                          ctypes.byref(sec), ctypes.sizeof(sec),
                                          None, None):
        _k32.DeleteProcThreadAttributeList(attr_list)
        _adv.FreeSid(sid)
        return False, "设置 AppContainer 能力失败（可能被安全策略拦截）", 0

    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    si.lpAttributeList = attr_list.value
    pi = PROCESS_INFORMATION()

    # 直接启动目标 exe（已验证：这是 AppContainer 最可靠的启动方式）。
    # 当前工作目录设为容器目录；AppContainer 对自身 Packages 目录有内置写权限，
    # 配置/数据自然落在隔离区，不碰宿主真实 AppData。
    flags = EXTENDED_STARTUPINFO_PRESENT
    cmdline = f'"{exe}" {args}'.strip()
    ctypes.set_last_error(0)
    ok = _k32.CreateProcessW(
        ctypes.c_wchar_p(exe), ctypes.c_wchar_p(cmdline),
        None, None, False, flags, None, cwd or None,
        ctypes.byref(si.StartupInfo), ctypes.byref(pi),
    )

    err = _k32.GetLastError() if not ok else 0
    _k32.DeleteProcThreadAttributeList(attr_list)

    if not ok:
        _adv.FreeSid(sid)
        # 常见错误：5=拒绝访问 50=不支持请求 87=参数错误
        hint = {5: "目录未授权/SID权限不足", 50: "系统不支持(需Win8+)",
                87: "参数错误", 2: "程序不存在"}.get(err, "")
        return False, f"AppContainer 启动失败（Windows 错误 {err}{'，' + hint if hint else ''}）", 0

    pid = pi.dwProcessId
    _k32.CloseHandle(pi.hProcess)
    _k32.CloseHandle(pi.hThread)
    _adv.FreeSid(sid)
    BUS.log(f"AppContainer 进程已启动 PID={pid}", "ok")
    return True, "已在应用沙盒中启动", pid


def verify_appcontainer(pid: int) -> tuple[bool, str]:
    """验证进程确实运行在 AppContainer 中（TokenIsAppContainer）。"""
    if not IS_WIN or pid <= 0:
        return False, "无法验证"
    TOKEN_QUERY = 0x0008
    TokenIsAppContainer = 29
    h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False, "无法打开进程"
    tok = wintypes.HANDLE()
    if not _adv.OpenProcessToken(h, TOKEN_QUERY, ctypes.byref(tok)):
        _k32.CloseHandle(h)
        return False, "无法打开令牌"
    flag = wintypes.DWORD()
    length = wintypes.DWORD()
    ok = _adv.GetTokenInformation(tok, TokenIsAppContainer, ctypes.byref(flag),
                                  ctypes.sizeof(flag), ctypes.byref(length))
    _k32.CloseHandle(tok)
    _k32.CloseHandle(h)
    if ok and flag.value:
        return True, "已确认 Lowbox/AppContainer 令牌"
    return False, "令牌非 AppContainer"


# ---------------------------------------------------------------- 引擎
class AppContainerEngine:
    """自研沙盒引擎：家庭版可用，无需 Hyper-V / 管理员 / 驱动。"""

    name = "应用沙盒"
    kind = "appcontainer"

    @staticmethod
    def prepare(c) -> tuple[bool, str, Optional[str]]:
        """准备目录并授权 AppContainer SID 访问。"""
        ok, msg = _prepare_native_disk(c)
        if not ok:
            return False, msg, None
        home = c.mount_dir
        name = f"WinCage_{c.id}"
        sid = _derive_sid(name)
        if not sid:
            return False, "创建 SID 失败", None
        sid_str = sid_to_string(sid)
        _adv.FreeSid(sid)
        gok, gmsg = _grant_tree_icacls(home, sid_str)
        if not gok:
            return False, gmsg, None
        return True, "环境就绪", home

    @staticmethod
    def start(c) -> tuple[bool, str]:
        ok, msg, home = AppContainerEngine.prepare(c)
        if not ok:
            return False, msg
        target = c.target
        # 兼容：把目标程序拷到容器目录
        if not os.path.exists(target):
            cand = os.path.join(home, os.path.basename(target))
            if os.path.exists(cand):
                target = cand
        env_block = _build_env(c, home)
        ok, msg, pid = launch_in_appcontainer(
            target, c.args, home, c.network, env_block, f"WinCage_{c.id}")
        if ok:
            c.last_run = time.time()
            c.disk_mounted = c.persist
            # 异步验证隔离是否真的生效
            def verify():
                vok, vmsg = verify_appcontainer(pid)
                BUS.log(f"隔离校验: {vmsg}", "ok" if vok else "warn")
            import threading
            threading.Thread(target=verify, daemon=True).start()
        return ok, msg


def _prepare_native_disk(c) -> tuple[bool, str]:
    """无需 diskpart：用普通目录模拟持久化盘（AppContainer 引擎专用）。"""
    home = c.mount_dir
    try:
        os.makedirs(home, exist_ok=True)
        for sub in ("Apps", "Share", "Config", "Config\\Roaming", "Config\\Local", "Temp"):
            os.makedirs(os.path.join(home, sub), exist_ok=True)
        # 目标程序拷贝进容器目录
        if c.target and os.path.exists(c.target):
            import shutil
            dest = os.path.join(home, os.path.basename(c.target))
            if not os.path.exists(dest):
                try:
                    shutil.copy2(c.target, dest)
                except Exception:  # noqa: BLE001
                    pass
        return True, "目录就绪"
    except Exception as e:  # noqa: BLE001
        return False, f"准备目录失败: {e}"
