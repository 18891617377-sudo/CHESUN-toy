WinCage - Windows 应用隔离容器

运行 WinCage.exe，出现 Win8 磁贴风格界面：
  1) 点「+ 新建容器」，选择要隔离运行的 EXE / MSI / MSIX / 安装器
  2) 选引擎：沙盒（轻量、秒开、适合普通软件）或 虚拟机（支持内核驱动软件）
  3) 双击磁贴运行

界面按钮：
  运行       启动选中的容器
  回滚/重置  VM=还原 CleanBase 快照；沙盒=清空持久化磁盘
  打开磁盘   在资源管理器查看虚拟磁盘挂载目录
  导出       把容器（配置+虚拟磁盘）打包成 .wincage 文件
  导入       从 .wincage 恢复容器（自动分配新 ID）
  删除       移除容器（磁盘文件保留）
  环境检查   重新探测沙盒 / Hyper-V / 应用沙盒可用性

关于右上角环境徽标：
  它显示的是"当前实际用来隔离你的引擎"（例如绿色「● 应用沙盒就绪」），
  而不是提示系统缺少哪些功能。没有 Windows 沙盒 / Hyper-V 但应用沙盒可用
  属于正常情况，程序依然处于隔离保护中，可放心使用。

★ 四套引擎 + 自动降级（核心特性）：
  新建容器时「引擎模式」选"自动"，运行时按本机能力依次降级：
    1) Windows 沙盒      —— 专业版且已启用，秒开、关掉归零
    2) Hyper-V 虚拟机    —— 有 Hyper-V，支持带内核驱动的程序
    3) 应用沙盒 AppContainer —— ★自研，家庭版可用！无需 Hyper-V、
       无需管理员、无需驱动，内核级低权限隔离（商店应用同款机制）
    4) 普通进程          —— 最后兜底，保证程序在任何机器上都能跑
  家庭版没有 Windows 沙盒也没有 Hyper-V，自动模式会选中第 3 套，
  因此本软件在所有 Windows 版本上都能提供隔离能力。

  应用沙盒（AppContainer）说明：
    纯 ctypes 调用 Windows 8+ 内置 API 实现：CreateAppContainerProfile
    创建独立 SID、STARTUPINFOEX + SECURITY_CAPABILITIES 低权限启动、
    icacls 精确授权容器目录。已实测启动进程为 Lowbox 令牌。
    隔离强度低于 Hyper-V（无法拦内核驱动），高于无隔离。
    默认无网络（可按需加 internetClient 能力）。

不需要第三方驱动、不需要修改 WDAC 基础策略，便于分发。
注意：Windows 沙盒/Hyper-V 是系统自带能力；AppContainer 是自研实现
（复用系统 API）。WinCage 是编排层与 GUI，单文件约 11MB。

沙盒引擎：
  基于 Windows 系统自带的 Windows 沙盒 + 持久化 VHDX 虚拟磁盘。
  程序和配置写在虚拟磁盘里，关掉沙盒后仍然保留。
  首次使用需在界面点「启用沙盒」并重启一次。

虚拟机引擎：
  基于 Hyper-V 完整虚拟机，用于 VPN / 杀软 / 反作弊等带内核驱动的程序。
  需要管理员权限，首次需启用 Hyper-V 并重启。

数据位置：
  %LOCALAPPDATA%\WinCage\
    containers.json   容器配置
    disks\            持久化虚拟磁盘（.vhdx）
    logs\             生成的 .wsb / boot.cmd / 日志

开源与分发：
  纯 Python 标准库实现，无第三方运行时依赖，可自由打包分发。
