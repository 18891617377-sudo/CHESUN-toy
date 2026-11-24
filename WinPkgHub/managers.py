"""WinPkgHub - 九个包管理器的探测 / 安装 / 搜索 / 装包逻辑。"""
from __future__ import annotations

import ctypes
import os
import shutil
import webbrowser

from core import (
    BUS,
    TOOLS_DIR,
    download,
    find_cygwin_root,
    find_msys2_root,
    github_asset,
    refresh_path,
    run_elevated_ps,
    run_out,
    run_ps,
    spawn,
)

CYGWIN_MIRROR = "https://mirrors.tuna.tsinghua.edu.cn/cygwin/"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def which(name: str) -> str | None:
    return shutil.which(name)


def first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


class Manager:
    def __init__(self, key, name, sub, color, admin=False, hint=""):
        self.key = key
        self.name = name
        self.sub = sub          # 磁贴第二行小字
        self.color = color
        self.admin = admin      # 是否通常需要管理员
        self.hint = hint
        self.installed = False
        self.version = ""

    # ---- 以下由子类覆盖
    def probe(self) -> tuple[bool, str]:
        return False, ""

    def install(self):
        BUS.log(f"暂不支持自动安装 {self.name}，请手动安装", "warn")

    def search(self, q: str):
        BUS.log(f"{self.name} 暂不支持命令行搜索", "warn")

    def add(self, pkg: str):
        BUS.log(f"{self.name} 暂不支持安装软件包", "warn")


# ------------------------------------------------------------------ winget
class Winget(Manager):
    def probe(self):
        if not which("winget"):
            return False, ""
        code, out = run_out(["winget", "--version"], 20)
        return (code == 0 and bool(out)), first_line(out)

    def install(self):
        BUS.log("winget 未检测到，尝试从 GitHub 安装官方 MSIX 包…", "warn")
        run_ps(
            "$ErrorActionPreference='Stop';"
            "$ProgressPreference='SilentlyContinue';"
            "$r=Invoke-RestMethod -Uri 'https://api.github.com/repos/microsoft/winget-cli/releases/latest' "
            "-Headers @{'User-Agent'='WinPkgHub'};"
            "$a=$r.assets | Where-Object { $_.name -like '*Msixbundle*' } | Select-Object -First 1;"
            "Invoke-WebRequest -Uri $a.browser_download_url -OutFile \"$env:TEMP\\winget.msixbundle\";"
            "Add-AppxPackage -Path \"$env:TEMP\\winget.msixbundle\";"
            "winget --version"
        )

    def search(self, q):
        spawn(["winget", "search", q, "--accept-source-agreements"])

    def add(self, pkg):
        spawn(
            ["winget", "install", pkg,
             "--accept-package-agreements", "--accept-source-agreements"]
        )


# -------------------------------------------------------------- chocolatey
class Chocolatey(Manager):
    def probe(self):
        if not which("choco"):
            return False, ""
        code, out = run_out(["choco", "--version"], 25)
        return (code == 0 and bool(out)), first_line(out)

    def install(self):
        script = (
            "Set-ExecutionPolicy Bypass -Scope Process -Force;"
            "[Net.ServicePointManager]::SecurityProtocol="
            "[Net.ServicePointManager]::SecurityProtocol -bor 3072;"
            "iex ((New-Object Net.WebClient).DownloadString("
            "'https://community.chocolatey.org/install.ps1'));"
            "choco --version"
        )
        if is_admin():
            run_ps(script)
        else:
            run_elevated_ps(script, "安装 Chocolatey")

    def search(self, q):
        spawn(["choco", "search", q, "--limit-output"])

    def add(self, pkg):
        script = f"choco install {pkg} -y --no-progress; exit $LASTEXITCODE"
        if is_admin():
            run_ps(script)
        else:
            run_elevated_ps(script, f"安装 {pkg}")


# ------------------------------------------------------------------- scoop
class Scoop(Manager):
    def probe(self):
        if not which("scoop"):
            return False, ""
        code, out = run_out(["scoop", "--version"], 25)
        return code == 0, first_line(out)

    def install(self):
        if not which("git"):
            BUS.log("scoop 依赖 git，先用 winget 安装 Git.Git…", "warn")
            spawn(["winget", "install", "Git.Git", "-e", "--id", "Git.Git",
                   "--accept-package-agreements", "--accept-source-agreements"])
            BUS.log("git 安装完成后请再点一次 scoop 磁贴", "warn")
            return
        run_ps(
            "Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force;"
            "irm get.scoop.sh | iex"
        )

    def search(self, q):
        spawn(["scoop", "search", q])

    def add(self, pkg):
        spawn(["scoop", "install", pkg])


# ------------------------------------------------------------------- msys2
class MSYS2(Manager):
    def probe(self):
        root = find_msys2_root()
        if not root:
            return False, ""
        code, out = run_out([os.path.join(root, "usr", "bin", "pacman.exe"), "--version"], 25)
        return code == 0, first_line(out)

    def install(self):
        BUS.log("下载 MSYS2 安装器…", "cmd")

        def worker():
            try:
                url = github_asset(
                    "msys2/msys2-installer",
                    lambda n: n.startswith("msys2-x86_64-") and n.endswith(".exe"),
                )
                exe = download(url, os.path.join(TOOLS_DIR, "msys2-installer.exe"), "MSYS2 安装器")
                root = os.path.join(TOOLS_DIR, "msys64").replace("\\", "/")
                BUS.log(f"静默安装到 {root}（约 1-3 分钟）", "cmd")
                spawn([
                    exe, "in", "--confirm-command", "--accept-licenses",
                    "--accept-messages", "--root", root,
                ])
            except Exception as e:  # noqa: BLE001
                BUS.log(f"MSYS2 自动安装失败：{e}", "err")
                webbrowser.open("https://www.msys2.org/")

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def _bash(self):
        root = find_msys2_root()
        if not root:
            BUS.log("找不到 MSYS2 根目录", "err")
            return None
        return os.path.join(root, "usr", "bin", "bash.exe")

    def search(self, q):
        b = self._bash()
        if b:
            spawn([b, "-lc", f"pacman -Ss {q} | head -n 60"])

    def add(self, pkg):
        b = self._bash()
        if b:
            spawn([b, "-lc", f"pacman -S --noconfirm {pkg}"])


# ------------------------------------------------------------------- vcpkg
class Vcpkg(Manager):
    def _exe(self):
        d = os.path.join(TOOLS_DIR, "vcpkg")
        p = os.path.join(d, "vcpkg.exe")
        return p if os.path.exists(p) else None

    def probe(self):
        p = self._exe()
        if not p:
            return False, ""
        code, out = run_out([p, "version"], 25)
        return code == 0, first_line(out)

    def install(self):
        if not which("git"):
            BUS.log("vcpkg 需要 git，请先安装 Git.Git", "err")
            return
        d = os.path.join(TOOLS_DIR, "vcpkg")

        def worker():
            if not os.path.isdir(d):
                spawn(["git", "clone", "--depth=1",
                       "https://github.com/microsoft/vcpkg", d])
                # 等 clone 结束（简单轮询）
                import time
                for _ in range(600):
                    if os.path.exists(os.path.join(d, "bootstrap-vcpkg.bat")):
                        break
                    time.sleep(0.5)
            spawn([os.path.join(d, "bootstrap-vcpkg.bat"), "-disableMetrics"], cwd=d)

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def search(self, q):
        p = self._exe()
        if p:
            spawn([p, "search", q])

    def add(self, pkg):
        p = self._exe()
        if p:
            spawn([p, "install", pkg])


# -------------------------------------------------------------------- nuget
class NuGet(Manager):
    def _exe(self):
        p = os.path.join(TOOLS_DIR, "nuget", "nuget.exe")
        return p if os.path.exists(p) else which("nuget")

    def probe(self):
        p = self._exe()
        if not p:
            return False, ""
        code, out = run_out([p, "help"], 25)
        return (code == 0 or "NuGet" in out), first_line(out) or "nuget.exe"

    def install(self):
        def worker():
            try:
                dest = os.path.join(TOOLS_DIR, "nuget", "nuget.exe")
                download("https://dist.nuget.org/win-x86-commandline/latest/nuget.exe", dest, "nuget.exe")
                refresh_path()
            except Exception as e:  # noqa: BLE001
                BUS.log(f"nuget 下载失败：{e}", "err")

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def search(self, q):
        p = self._exe()
        if p:
            spawn([p, "list", q])

    def add(self, pkg):
        p = self._exe()
        if p:
            out = os.path.join(TOOLS_DIR, "nuget", "packages")
            spawn([p, "install", pkg, "-OutputDirectory", out])


# ---------------------------------------------------------------------- nix
class Nix(Manager):
    def _wsl(self):
        code, out = run_out(["wsl", "-l", "-q"], 20)
        return code == 0 and bool(out)

    def probe(self):
        if not self._wsl():
            return False, ""
        code, out = run_out(["wsl", "-e", "bash", "-lc", "command -v nix && nix --version"], 30)
        return code == 0, first_line(out)

    def install(self):
        BUS.log("Nix 在 Windows 上不走原生安装，必须依赖 WSL2。", "warn")
        BUS.log("① wsl --install -d Ubuntu   (管理员 PowerShell，装完需重启)", "dim")
        BUS.log("② 进入 Ubuntu 后：curl -L https://nixos.org/nix/install | sh", "dim")
        BUS.log("③ 回到本程序点『检测』即可识别", "dim")

    def search(self, q):
        spawn(["wsl", "-e", "bash", "-lc", f"nix search nixpkgs {q}"])

    def add(self, pkg):
        spawn(["wsl", "-e", "bash", "-lc",
               f"nix profile install nixpkgs#{pkg}"])


# ------------------------------------------------------------------- cygwin
class Cygwin(Manager):
    def probe(self):
        root = find_cygwin_root()
        if not root:
            return False, ""
        code, out = run_out([os.path.join(root, "bin", "bash.exe"), "--version"], 20)
        return code == 0, first_line(out)

    def install(self):
        def worker():
            try:
                exe = download("https://cygwin.com/setup-x86_64.exe",
                               os.path.join(TOOLS_DIR, "setup-x86_64.exe"), "Cygwin Setup")
                root = os.path.join(TOOLS_DIR, "cygwin64")
                BUS.log(f"静默安装到 {root}", "cmd")
                spawn([exe, "-q", "-O", "-s", CYGWIN_MIRROR,
                       "-R", root, "-B", "-P", "bash,coreutils,git,vim,curl"])
            except Exception as e:  # noqa: BLE001
                BUS.log(f"自动安装失败：{e}", "err")
                webbrowser.open("https://www.cygwin.com/install.html")

        import threading

        threading.Thread(target=worker, daemon=True).start()

    def search(self, q):
        BUS.log("Cygwin 没有在线搜索 CLI，请在 setup 里勾选包。", "warn")

    def add(self, pkg):
        exe = os.path.join(TOOLS_DIR, "setup-x86_64.exe")
        root = os.path.join(TOOLS_DIR, "cygwin64")
        if not os.path.exists(exe):
            BUS.log("先点 CYGWIN 磁贴安装环境", "err")
            return
        spawn([exe, "-q", "-O", "-s", CYGWIN_MIRROR, "-R", root, "-B", "-P", pkg])


# ------------------------------------------------------------------- ninite
class Ninite(Manager):
    def probe(self):
        return False, "网页版"

    def install(self):
        BUS.log("Ninite 没有命令行接口，正在打开网页…", "warn")
        webbrowser.open("https://ninite.com/")

    def search(self, q):
        webbrowser.open("https://ninite.com/")

    def add(self, pkg):
        webbrowser.open("https://ninite.com/")


def build() -> list[Manager]:
    return [
        Winget("winget", "winget", "官方 · 装机首选", "#0B78D0", hint="微软官方，Win10/11 自带"),
        Chocolatey("choco", "Chocolatey", "企业级 · 脚本自动化", "#9A5B2E", admin=True,
                   hint="老牌，企业自动化很强"),
        Scoop("scoop", "Scoop", "用户目录 · 免 UAC", "#107C10", hint="便携开发工具首选"),
        MSYS2("msys2", "MSYS2", "pacman · Unix 工具链", "#C239B3", hint="带 mingw 编译链"),
        Vcpkg("vcpkg", "vcpkg", "C/C++ 依赖管理", "#5C2D91", hint="微软 C++ 库管理器"),
        NuGet("nuget", "NuGet", ".NET 包管理", "#00A4EF", hint=".NET 生态标准包源"),
        Nix("nix", "Nix", "声明式 · 可复现", "#5277C3", hint="类似更强力的 venv"),
        Cygwin("cygwin", "Cygwin", "Unix 兼容层", "#B7472A", hint="老牌 Unix 环境"),
        Ninite("ninite", "Ninite", "批量装机 · 网页", "#E81123", hint="勾选即装，无 CLI"),
    ]


MANAGERS = build()
