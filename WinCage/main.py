"""WinCage - Windows 应用隔离容器（Win8 磁贴风格）。

用法：
  python main.py          启动 GUI
  python main.py --probe  命令行探测隔离环境并退出
"""
from __future__ import annotations

import sys

if __name__ == "__main__":
    if "--probe" in sys.argv:
        import json
        import engine
        print(json.dumps(engine.probe_environment(), indent=2, ensure_ascii=False))
    else:
        from ui import launch
        launch()
