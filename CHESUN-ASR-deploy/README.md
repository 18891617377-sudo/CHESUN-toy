# CHESUN 采桑一键配置 ASR

Windows 10 1809+ / Windows 11 的 Defender ASR、网络保护、PUA、云保护、HVCI 与基础安全策略一键配置脚本。

## 文件

- `CHESUN采桑一键配置ASR.ps1`：主脚本，首次运行会展示风险声明并请求管理员权限。
- `运行配置.bat`：本地启动器，调用同目录 PowerShell 脚本。
- `CHESUN采桑ASR基线清单.txt`：本次配置涉及的基线说明与核对清单。

## 运行

在资源管理器中双击 `运行配置.bat`，或在管理员 PowerShell 中执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\CHESUN采桑一键配置ASR.ps1
```

> 运行前建议创建系统还原点；部分配置需重启后生效。脚本按现状提供，不提供明示或默示担保。
