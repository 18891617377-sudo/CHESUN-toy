# CHESUN-toy

CHESUN 相关 Windows 工具与脚本合集，统一采用 **BSD 3-Clause License**（见根目录 `LICENSE`）。

## 目录

### `WinPkgHub/`

Windows 包管理器中枢：九个包管理器统一探测、搜索与一键部署。

- 运行：`python main.py`，或双击 `run.bat`
- 要求：Windows 10/11 + Python 3.10+，仅使用标准库与 Tkinter
- 说明：详见 [`WinPkgHub/README.md`](./WinPkgHub/README.md)

### `CHESUN-ASR-deploy/`

CHESUN 采桑 Windows Defender ASR 与安全基线一键部署脚本。

- 运行：双击 `运行配置.bat`，或在管理员 PowerShell 中执行主脚本
- 内容：ASR 规则、网络保护、PUA、云保护、HVCI 等基线配置
- 说明：详见 [`CHESUN-ASR-deploy/README.md`](./CHESUN-ASR-deploy/README.md)

## 许可证

本仓库整体按 BSD 3-Clause License 发布。保留根目录版权声明与许可证文本；第三方材料若有另行说明，以对应目录内说明为准。
