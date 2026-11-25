# WinCage

**Windows 应用隔离容器 —— Win8 磁贴风格的轻量应用沙盒**

![WinCage icon](app_icon.png)

单一 EXE，纯 Python 标准库（零第三方运行时依赖），把任意 EXE / MSI / MSIX / 安装包丢进隔离环境里运行。

## 四套引擎，自动降级

新建容器时把「引擎模式」设为 **自动**，运行时按本机能力依次选择：

| 优先级 | 引擎 | 适用 | 要求 |
|---|---|---|---|
| 1 | Windows 沙盒 | 普通软件，秒开、关掉归零 | Win 专业版 + 已启用 |
| 2 | Hyper-V 虚拟机 | VPN / 杀软 / 反作弊等带内核驱动的软件 | 有 Hyper-V |
| 3 | **AppContainer（自研）** | 普通软件，家庭版可用 | **无要求** |
| 4 | 普通进程 | 最后兜底，保证能跑 | 无 |

第 3 套是本项目的核心：用 `ctypes` 直接调用 Windows 8+ 内置 API（`CreateAppContainerProfile` + `STARTUPINFOEX` / `SECURITY_CAPABILITIES`）创建真正的 Lowbox 令牌进程，**不需要 Hyper-V、不需要管理员、不需要任何第三方驱动**。已实测 `verify=True`（内核确认为 AppContainer 令牌）。

家庭版既没有 Windows 沙盒也没有 Hyper-V，自动模式会选中第 3 套，因此所有 Windows 版本都能获得隔离能力。

> 隔离强度如实说明：AppContainer 是内核级低权限，拦得住普通流氓软件，但拦不住内核驱动——那一档只有 Hyper-V 能接。

## 界面

- 磁贴墙面：双击磁贴运行容器，单击查看
- **新建容器**：选目标程序（EXE/MSI/MSIX/安装器）、选引擎模式、配置持久化磁盘
- **回滚/重置**：VM 还原 `CleanBase` 快照；沙盒清空持久化磁盘
- **导出 / 导入**：容器（配置+虚拟磁盘）打包成 `.wincage` 分享
- **☀/☾ 主题**：经典深色 / 清爽亮色，自动记住
- **环境检查**：重新探测四套引擎可用性

数据存放在 `%LOCALAPPDATA%\WinCage\`：`containers.json`、`disks\`、`logs\`。

## 构建

```bat
build.bat
```

前提：Python 3.12+ 与 PyInstaller（`pip install pyinstaller`）。产物为 `dist\WinCage.exe`（单文件，约 11MB，已嵌入图标）。

测试：

```bat
python test_wincage.py
```

## 许可证

BSD 3-Clause —— 见 [LICENSE](LICENSE)。Copyright (c) 2026, Chesun. 可自由使用、修改、分发。
