"""WinPkgHub 功能测试：core / managers / ui 三层的回归测试。
用法：python test_winpkghub.py   （需要系统 Python 3.10+，带 tkinter）
"""
from __future__ import annotations

import io
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core  # noqa: E402
import managers  # noqa: E402


# ----------------------------------------------------------------- helpers
def drain_bus():
    while True:
        try:
            core.BUS.queue.get_nowait()
        except Exception:
            break
    while True:
        try:
            core.BUS.status.get_nowait()
        except Exception:
            break


def bus_messages():
    out = []
    while True:
        try:
            out.append(core.BUS.queue.get_nowait())
        except Exception:
            break
    return out


class TestCore(unittest.TestCase):
    def setUp(self):
        drain_bus()

    def test_bus_roundtrip(self):
        core.BUS.log("hello", "warn")
        core.BUS.set_status("busy")
        msgs = bus_messages()
        self.assertEqual(msgs, [("warn", "hello")])
        self.assertEqual(core.BUS.status.get_nowait(), "busy")

    def test_run_out_success(self):
        code, out = core.run_out([sys.executable, "-c", "print('hi')"], 5)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "hi")

    def test_run_out_failure(self):
        code, out = core.run_out([sys.executable, "-c",
                                  "import sys;sys.stderr.write('boom');sys.exit(3)"], 5)
        self.assertEqual(code, 3)
        self.assertIn("boom", out)

    def test_run_out_notfound(self):
        code, out = core.run_out(["definitely_not_a_real_command_xyz"], 5)
        self.assertEqual(code, 127)
        self.assertEqual(out, "")

    def test_run_out_timeout(self):
        code, out = core.run_out([sys.executable, "-c", "import time;time.sleep(5)"], 1)
        self.assertEqual(code, 124)
        self.assertEqual(out, "timeout")

    def test_spawn_streams_output(self):
        t = core.spawn([sys.executable, "-c",
                        "import sys;print('line1');print('line2');sys.stdout.flush()"])
        t.join(timeout=5)
        msgs = bus_messages()
        texts = [m for _, m in msgs]
        self.assertTrue(any("line1" in t for t in texts))
        self.assertTrue(any("line2" in t for t in texts))
        self.assertTrue(any("退出码 0" in t for t in texts))
        self.assertEqual(core.BUS.status.get_nowait(), "空闲")

    def test_spawn_missing_command(self):
        t = core.spawn(["no_such_command_abc"])
        t.join(timeout=5)
        texts = [m for _, m in bus_messages()]
        self.assertTrue(any("命令不存在" in t for t in texts))

    def test_run_ps_calls_powershell(self):
        with mock.patch.object(core, "spawn") as sp:
            core.run_ps("Write-Output test")
        args = sp.call_args[0][0]
        self.assertEqual(args[0], "powershell")
        self.assertIn("-Command", args)
        self.assertEqual(args[-1], "Write-Output test")

    def test_run_elevated_ps_uses_runas(self):
        with mock.patch.object(core.subprocess, "run") as run, \
             mock.patch.object(core, "LOGS_DIR", os.path.dirname(__file__)):
            t = core.run_elevated_ps("Write-Output hi", "测试")
            t.join(timeout=5)
        self.assertTrue(run.called)
        cmd = run.call_args[0][0]
        self.assertIn("powershell", cmd[0])
        self.assertIn("-Verb RunAs", cmd[3])
        # 清理临时脚本
        for f in os.listdir(os.path.dirname(__file__)):
            if f.startswith("elev_") and f.endswith(".ps1"):
                os.remove(os.path.join(os.path.dirname(__file__), f))

    def test_download_writes_file(self):
        import tempfile
        payload = b"hello-binary" * 100
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.bin")
            with open(src, "wb") as f:
                f.write(payload)
            dest = os.path.join(d, "sub", "out.bin")
            core.download("file:///" + src.replace("\\", "/"), dest, "test.bin")
            with open(dest, "rb") as f:
                self.assertEqual(f.read(), payload)
        self.assertTrue(any("下载完成" in m for _, m in bus_messages()))

    def test_resolve_cmd_expands_bare_name(self):
        """回归：Windows 上 scoop 等 .CMD shim 用裸命令名启动会失败(127)。"""
        if not core.IS_WIN:
            self.skipTest("仅 Windows 验证")
        resolved = core.resolve_cmd(["scoop", "--version"])
        self.assertEqual(os.path.splitext(resolved[0])[1].lower(), ".cmd")
        self.assertNotEqual(resolved[0], "scoop")

    def test_resolve_cmd_keeps_absolute_path(self):
        abs_path = r"C:\msys64\usr\bin\bash.exe"
        self.assertEqual(core.resolve_cmd([abs_path, "-lc", "x"]),
                         [abs_path, "-lc", "x"])

    def test_scoop_probe_detects_installed_shim(self):
        """回归：本机已装 scoop 时，probe 必须返回 True（此前误报未安装）。"""
        p = managers.which("scoop")
        if not p:
            self.skipTest("本机未安装 scoop")
        m = next(x for x in managers.MANAGERS if x.key == "scoop")
        ok, ver = m.probe()
        self.assertTrue(ok, f"scoop 已安装但探测失败：{ver!r}")
        self.assertIn("Current Scoop version", ver)

    def test_elevated_script_has_locale_independent_marker(self):
        """回归：提权完成检测不能只靠中文 '脚本结束' 文案。"""
        with mock.patch.object(core.subprocess, "run"), \
             mock.patch.object(core, "LOGS_DIR", os.path.dirname(__file__)):
            t = core.run_elevated_ps("Write-Output hi")
            t.join(timeout=5)
        ps1s = [f for f in os.listdir(os.path.dirname(__file__))
                if f.startswith("elev_") and f.endswith(".ps1")]
        self.assertTrue(ps1s)
        with open(os.path.join(os.path.dirname(__file__), ps1s[-1]),
                  encoding="utf-8-sig") as f:
            content = f.read()
        self.assertIn("__WPH_DONE__", content)
        for f in ps1s:
            os.remove(os.path.join(os.path.dirname(__file__), f))

    def test_github_asset_matching(self):
        fake = {"assets": [
            {"name": "foo-x64.msixbundle", "browser_download_url": "http://a"},
            {"name": "foo-arm64.msixbundle", "browser_download_url": "http://b"},
            {"name": "foo.txt", "browser_download_url": "http://c"},
        ]}
        cm = mock.MagicMock()
        cm.__enter__.return_value.read.return_value = __import__("json").dumps(fake).encode()
        with mock.patch.object(core.urllib.request, "urlopen", return_value=cm):
            url = core.github_asset("x/y", lambda n: n.endswith(".msixbundle"))
        self.assertEqual(url, "http://a")

    def test_refresh_path_noop_off_windows(self):
        # 在非 Windows 上 refresh_path 应安全跳过
        if core.IS_WIN:
            self.skipTest("仅非 Windows 验证")
        before = os.environ.get("PATH", "")
        core.refresh_path()
        self.assertEqual(os.environ.get("PATH", ""), before)


class TestManagers(unittest.TestCase):
    def setUp(self):
        drain_bus()

    def test_build_has_nine(self):
        ms = managers.build()
        self.assertEqual(len(ms), 9)
        self.assertEqual(len({m.key for m in ms}), 9)

    def test_first_line(self):
        self.assertEqual(managers.first_line("  \n  v1.2.3 \n next"), "v1.2.3")
        self.assertEqual(managers.first_line(""), "")

    def test_which(self):
        self.assertIsNotNone(managers.which("python"))
        self.assertIsNone(managers.which("definitely_not_real_xyz"))

    def test_is_admin_returns_bool(self):
        self.assertIsInstance(managers.is_admin(), bool)

    def test_probe_all(self):
        for m in managers.MANAGERS:
            ok, ver = m.probe()
            self.assertIsInstance(ok, bool, m.key)
            self.assertIsInstance(ver, str, m.key)

    def _patch_spawn(self):
        return mock.patch.object(managers, "spawn")

    def test_winget_commands(self):
        with self._patch_spawn() as sp:
            w = next(m for m in managers.MANAGERS if m.key == "winget")
            w.search("ripgrep")
            cmd = sp.call_args[0][0]
            self.assertEqual(cmd[:3], ["winget", "search", "ripgrep"])
            w.add("ripgrep")
            cmd = sp.call_args[0][0]
            self.assertEqual(cmd[:3], ["winget", "install", "ripgrep"])
            self.assertIn("--accept-package-agreements", cmd)

    def test_choco_commands(self):
        with self._patch_spawn() as sp, \
             mock.patch.object(managers, "run_ps") as ps, \
             mock.patch.object(managers, "is_admin", return_value=True):
            c = next(m for m in managers.MANAGERS if m.key == "choco")
            c.search("7zip")
            self.assertEqual(sp.call_args[0][0][:3], ["choco", "search", "7zip"])
            c.add("7zip")
            self.assertIn("choco install 7zip -y", ps.call_args[0][0])

    def test_scoop_commands(self):
        with self._patch_spawn() as sp, mock.patch.object(managers, "run_ps"):
            s = next(m for m in managers.MANAGERS if m.key == "scoop")
            s.search("neovim")
            self.assertEqual(sp.call_args[0][0], ["scoop", "search", "neovim"])
            s.add("neovim")
            self.assertEqual(sp.call_args[0][0], ["scoop", "install", "neovim"])

    def test_msys2_commands(self):
        with self._patch_spawn() as sp, \
             mock.patch.object(managers, "find_msys2_root", return_value=r"C:\msys64"):
            m = next(x for x in managers.MANAGERS if x.key == "msys2")
            m.search("curl")
            cmd = sp.call_args[0][0]
            self.assertIn("pacman -Ss curl", cmd[-1])
            m.add("curl")
            cmd = sp.call_args[0][0]
            self.assertIn("pacman -S --noconfirm curl", cmd[-1])

    def test_vcpkg_commands(self):
        with self._patch_spawn() as sp, \
             mock.patch("os.path.exists", return_value=True):
            v = next(m for m in managers.MANAGERS if m.key == "vcpkg")
            v.search("fmt")
            self.assertEqual(sp.call_args[0][0][-2:], ["search", "fmt"])
            v.add("fmt")
            self.assertEqual(sp.call_args[0][0][-2:], ["install", "fmt"])

    def test_nuget_commands(self):
        with self._patch_spawn() as sp, \
             mock.patch.object(managers.NuGet, "_exe", return_value="nuget.exe"):
            n = next(m for m in managers.MANAGERS if m.key == "nuget")
            n.search("Newtonsoft.Json")
            self.assertEqual(sp.call_args[0][0][-2:], ["list", "Newtonsoft.Json"])
            n.add("Newtonsoft.Json")
            cmd = sp.call_args[0][0]
            self.assertEqual(cmd[1:3], ["install", "Newtonsoft.Json"])
            self.assertIn("-OutputDirectory", cmd)

    def test_nix_commands(self):
        with self._patch_spawn() as sp:
            n = next(m for m in managers.MANAGERS if m.key == "nix")
            n.search("hello")
            self.assertIn("nix search nixpkgs hello", sp.call_args[0][0][-1])
            n.add("hello")
            self.assertIn("nix profile install nixpkgs#hello", sp.call_args[0][0][-1])

    def test_cygwin_add(self):
        with self._patch_spawn() as sp, \
             mock.patch.object(managers.os.path, "exists", return_value=True):
            c = next(m for m in managers.MANAGERS if m.key == "cygwin")
            c.add("curl")
            cmd = sp.call_args[0][0]
            self.assertIn("-P", cmd)
            self.assertEqual(cmd[-1], "curl")
            c.search("curl")  # 应只记日志不崩溃
            self.assertTrue(any("没有在线搜索" in m for _, m in bus_messages()))

    def test_ninite_opens_browser(self):
        with mock.patch.object(managers.webbrowser, "open") as op:
            n = next(m for m in managers.MANAGERS if m.key == "ninite")
            n.install()
            n.search("x")
            n.add("x")
        self.assertEqual(op.call_count, 3)

    def test_scoop_install_requires_git(self):
        with mock.patch.object(managers, "which", return_value=None), \
             self._patch_spawn() as sp:
            s = next(m for m in managers.MANAGERS if m.key == "scoop")
            s.install()
            cmd = sp.call_args[0][0]
            self.assertTrue(any("Git.Git" in str(x) for x in cmd))

    def test_vcpkg_install_requires_git(self):
        with mock.patch.object(managers, "which", return_value=None):
            v = next(m for m in managers.MANAGERS if m.key == "vcpkg")
            v.install()
            self.assertTrue(any("git" in m for _, m in bus_messages()))


class TestUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except Exception as e:
            raise unittest.SkipTest(f"无 GUI 环境: {e}")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        import ui
        drain_bus()
        self.app = ui.App()
        self.app.root.withdraw()

    def tearDown(self):
        self.app.root.destroy()

    def test_tiles_count_and_size(self):
        self.assertEqual(len(self.app.tiles), 9)
        t = self.app.tiles[0]
        self.assertEqual(t.winfo_reqwidth(), 214)
        self.assertEqual(t.winfo_reqheight(), 140)

    def test_select_updates_state(self):
        self.app.select(4)
        self.assertEqual(self.app.selected, 4)
        self.assertTrue(self.app.tiles[4].selected)
        self.assertFalse(self.app.tiles[0].selected)
        self.assertIn("vcpkg", self.app.cur_mgr.cget("text"))

    def test_tile_set_state(self):
        t = self.app.tiles[0]
        t.set_state(True, "v1.9.0")
        self.assertIn("已安装", t.state.cget("text"))
        t.set_state(False, "")
        self.assertIn("未安装", t.state.cget("text"))
        t2 = self.app.tiles[-1]  # ninite
        t2.set_state(False, "")
        self.assertIn("网页", t2.state.cget("text"))

    def test_placeholder(self):
        self.assertEqual(self.app._q(), "")
        self.app.query.delete(0, "end")
        self.app.query.insert(0, "ripgrep")
        self.assertEqual(self.app._q(), "ripgrep")

    def test_search_empty_guard(self):
        self.app.do_search()
        self.assertIn("请输入包名", self.app.status.cget("text"))

    def test_search_calls_current(self):
        with mock.patch.object(self.app.current, "search") as s:
            self.app.query.delete(0, "end")
            self.app.query.insert(0, "ripgrep")
            self.app.do_search()
        s.assert_called_once_with("ripgrep")

    def test_install_pkg_guard(self):
        self.app.query.delete(0, "end")
        self.app.query.insert(0, "ripgrep")
        self.app.current.installed = False
        with mock.patch.object(self.app, "install_manager") as im:
            self.app.do_install_pkg()
        self.assertTrue(im.called)

    def test_install_manager_already_installed(self):
        self.app.current.installed = True
        with mock.patch.object(self.app.current, "install") as inst:
            self.app.install_manager()
        self.assertFalse(inst.called)

    def test_pump_updates_tile(self):
        self.app.ui_events.put(("tile", 0, True, "v1.0"))
        self.app._pump()
        self.assertIn("已安装", self.app.tiles[0].state.cget("text"))

    def test_refresh_all_thread(self):
        with mock.patch.object(type(self.app.current), "probe", return_value=(True, "v9")):
            self.app.refresh_all()
            for _ in range(100):
                self.app.root.update()
                if self.app.ui_events.empty():
                    break
                time.sleep(0.01)
        self.assertTrue(any(m.installed for m in managers.MANAGERS))

    def test_console_write_and_clear(self):
        self.app._write("hello", "ok")
        self.app.clear_console()
        self.assertEqual(self.app.text.get("1.0", "end").strip(), "")

    def test_shade(self):
        import ui
        self.assertEqual(ui.shade("#000000", 1.0), "#ffffff")
        self.assertEqual(ui.shade("#ffffff", -1.0), "#000000")

    def test_font_picker(self):
        import ui
        self.assertIsInstance(ui.pick_font(), str)
        self.assertIsInstance(ui.mono_font(), str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
