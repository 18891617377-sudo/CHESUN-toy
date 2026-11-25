"""WinCage 测试：配置模型 + 引擎生成脚本 + GUI 结构。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from config import Container, new_container, detect_target_type, KIND_SANDBOX, KIND_VM
from config import TARGET_EXE, TARGET_MSIX, TARGET_INSTALLER
import engine


class TestConfig(unittest.TestCase):
    def test_new_container(self):
        c = new_container("测试", "C:\\app\\tool.exe", kind=KIND_SANDBOX,
                          target_type=TARGET_EXE, persist=True, persist_gb=30)
        self.assertEqual(c.name, "测试")
        self.assertEqual(c.kind, KIND_SANDBOX)
        self.assertEqual(c.persist_gb, 30)
        self.assertTrue(c.persist)
        self.assertEqual(len(c.id), 12)

    def test_roundtrip(self):
        c = new_container("往返", "C:\\a.exe", target_type=TARGET_EXE)
        d = Container.from_dict(c.to_dict())
        self.assertEqual(d.name, c.name)
        self.assertEqual(d.id, c.id)
        self.assertEqual(d.target, c.target)

    def test_detect_type(self):
        self.assertEqual(detect_target_type("app.msix"), TARGET_MSIX)
        self.assertEqual(detect_target_type("app.msixbundle"), TARGET_MSIX)
        self.assertEqual(detect_target_type("setup_x64.exe"), TARGET_INSTALLER)
        self.assertEqual(detect_target_type("tool.exe"), TARGET_EXE)
        self.assertEqual(detect_target_type("app.msi"), TARGET_INSTALLER)

    def test_paths(self):
        c = new_container("x", "C:\\a.exe")
        self.assertTrue(c.disk_path.endswith(".vhdx"))
        self.assertEqual(os.path.basename(c.mount_dir), c.id)


class TestSandboxEngine(unittest.TestCase):
    def test_boot_exe(self):
        c = new_container("浏览器", "C:\\app\\chrome.exe", target_type=TARGET_EXE,
                          args="--new-window", persist=True)
        lines = engine.SandboxEngine.build_boot_script(c)
        text = "\n".join(lines)
        self.assertIn("chrome.exe", text)
        self.assertIn("--new-window", text)
        self.assertIn("start", text)

    def test_boot_msix(self):
        c = new_container("包", "C:\\app\\x.msix", target_type=TARGET_MSIX)
        text = "\n".join(engine.SandboxEngine.build_boot_script(c))
        self.assertIn("Add-AppxPackage", text)

    def test_wsb(self):
        c = new_container("测试", "C:\\a.exe", persist=True, memory_mb=8192,
                          network=False)
        wsb = engine.SandboxEngine.build_wsb(c, "C:\\boot.cmd")
        self.assertIn("<Configuration>", wsb)
        self.assertIn("<Networking>Disable</Networking>", wsb)
        self.assertIn("<MemoryInMB>8192</MemoryInMB>", wsb)
        self.assertIn("<MappedFolders>", wsb)
        self.assertIn(c.mount_dir, wsb)
        self.assertIn("C:\\boot.cmd", wsb)

    def test_wsb_no_persist(self):
        c = new_container("无盘", "C:\\a.exe", persist=False)
        wsb = engine.SandboxEngine.build_wsb(c, "C:\\boot.cmd")
        self.assertNotIn("<MappedFolders>", wsb)


class TestVMEngine(unittest.TestCase):
    def test_create_script(self):
        c = new_container("驱动测试", "C:\\vpn\\setup.exe", kind=KIND_VM,
                          persist_gb=60)
        s = engine.VMEngine.build_create_script(c, "D:\\win11.iso")
        self.assertIn("New-VM", s)
        self.assertIn("Generation 2", s)
        self.assertIn("Checkpoint-VM", s)
        self.assertIn("CleanBase", s)
        self.assertIn("win11.iso", s)


class TestEngineFallback(unittest.TestCase):
    def test_choose_auto(self):
        c = new_container("自动", "C:\\a.exe")
        kind = engine.choose_engine(c)
        self.assertIn(kind, ("sandbox", "appcontainer", "plain"))

    def test_choose_forced(self):
        c = new_container("指定", "C:\\a.exe", engine_mode=config.MODE_PLAIN)
        self.assertEqual(engine.choose_engine(c), "plain")
        c.engine_mode = config.MODE_APP
        self.assertEqual(engine.choose_engine(c), "appcontainer")

    def test_all_engines_registered(self):
        for k in ("sandbox", "vm", "appcontainer", "plain"):
            self.assertIn(k, engine.ENGINES)

    def test_appcontainer_available(self):
        import engine_native
        if os.name == "nt":
            self.assertTrue(engine_native.available())

    def test_container_engine_mode_roundtrip(self):
        c = new_container("模式", "C:\\a.exe", engine_mode=config.MODE_APP)
        d = Container.from_dict(c.to_dict())
        self.assertEqual(d.engine_mode, config.MODE_APP)


if __name__ == "__main__":
    unittest.main(verbosity=2)
