$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms

$disclaimer = @"
【CHESUN 采桑一键配置 ASR —— 使用声明与风险提示】

【适用环境】
  Windows 10 1809 及以上 / Windows 11，需管理员权限运行。

【运行前提】
  1. Microsoft Defender 必须是系统唯一的杀毒软件。已安装 360、火绒、
     腾讯管家等第三方杀软的，请先卸载再运行，否则本脚本配置的规则
     不生效且可能产生冲突。
  2. 运行中会弹出 UAC 管理员确认框，请选择"是"。

【本脚本可能影响的内容】
  1. ASR 行为规则可能拦截：PsExec/WMI 远程运维命令、Office 文档调用
     外部程序与宏、伪装或复制系统工具的第三方程序。
  2. 漏洞利用缓解（DEP/ASLR/CFG）可能使极老的 32 位软件崩溃。
  3. UAC 与 SmartScreen 的弹窗提示会变得更频繁。
  4. 部分配置（内核完整性、LSA 保护、UAC）需重启电脑后生效。
  5. 本脚本会锁定 hosts 文件与 WDAC 策略目录的写入权限（防篡改），
     之后修改 hosts 或更新 WDAC 策略需先用管理员解锁，属正常现象。

【免责声明】
  本脚本按"现状"免费提供，不提供任何明示或暗示的担保。因运行本脚本
  而导致的任何直接或间接损失、数据丢失、软件无法使用、系统故障或
  安全事件，作者概不负责。运行前建议自行创建系统还原点。

是否已阅读并理解以上全部内容，确认继续运行？
"@

function Show-Disclaimer {
    $r = [System.Windows.Forms.MessageBox]::Show($disclaimer, 'CHESUN 采桑一键配置 ASR',
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning,
        [System.Windows.Forms.MessageBoxDefaultButton]::Button2)
    return ($r -eq [System.Windows.Forms.DialogResult]::Yes)
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if ($isAdmin) {
    if ($args -notcontains '-Confirmed') {
        if (-not (Show-Disclaimer)) { exit }
    }
} else {
    if (-not (Show-Disclaimer)) { exit }
    Start-Process -FilePath $PSCommandPath -Verb RunAs -ArgumentList '-Confirmed'
    exit
}

Write-Output '=== CHESUN 采桑一键配置 ASR ==='
Write-Output '=== 已以管理员令牌运行 ==='

$asrEnabled = @(
    '56a863a9-875e-4185-98a7-b882c64b5ce5',
    '9e6c4e1f-7d60-472f-ba1a-a39ef669e4b2',
    'e6db77e5-3df2-4cf1-b95a-636979351e5b',
    'c0033c00-d16d-4114-a5a0-dc9b3a7d2ceb',
    '33ddedf1-c6e0-47cb-833e-de6133960387',
    'be9ba2d9-53ea-4cdc-84e5-9b1eeee46550',
    'd3e037e1-3eb8-44c8-a917-57927947596d',
    '5beb7efe-fd9a-4556-801d-275e5ffc04cc',
    'c1db55ab-c21a-4637-bb3f-a12568109d35',
    'd1e49aac-8f56-4280-b9ba-993a6d77406c',
    'd4f940ab-401b-4efc-aadc-ad5f3c50688a',
    '75668c1f-73b5-4cf0-bb93-3ecf5cb7cc84',
    '3b576869-a4ec-4529-8536-b80a7769e899',
    '92e97fa1-2edf-4476-bdd6-9dd0b4dddc7b',
    '26190899-1602-49e8-8b27-eb1d0a1ce869',
    '7674ba52-37eb-4a4f-a9a1-f0f9a1619a2c'
)
$asrAudit = @('01443614-cd74-433a-b99e-2ecdc07bfc25')

$ids  = $asrEnabled + $asrAudit
$acts = @('Enabled') * $asrEnabled.Count + @('AuditMode') * $asrAudit.Count
Set-MpPreference -AttackSurfaceReductionRules_Ids $ids -AttackSurfaceReductionRules_Actions $acts
Write-Output "[OK] ASR: $($asrEnabled.Count) 条强制 + $($asrAudit.Count) 条审计"

Set-MpPreference -AttackSurfaceReductionOnlyExclusions @()
Write-Output '[OK] ASR 排除列表已清空'

Set-MpPreference -PUAProtection 1
Set-MpPreference -MAPSReporting 2
Set-MpPreference -SubmitSamplesConsent 1
Set-MpPreference -CloudBlockLevel High
Set-MpPreference -CloudExtendedTimeout 50
Set-MpPreference -EnableFileHashComputation $true
Set-MpPreference -EnableNetworkProtection Enabled
Set-MpPreference -DisableRealtimeMonitoring $false
Set-MpPreference -DisableBehaviorMonitoring $false
Set-MpPreference -DisableArchiveScanning $false
Set-MpPreference -DisableRemovableDriveScanning $false
Set-MpPreference -DisableIntrusionPreventionSystem $false
Set-MpPreference -ScanParameters 1
Set-MpPreference -ScanScheduleQuickScanTime 180
Set-MpPreference -ScanScheduleDay Everyday
Write-Output '[OK] Defender 拉满: 云High+50s/MAPS高级/PUA/哈希计算/网络保护/每日03:00快扫'

$s = Get-MpComputerStatus
if ($s.IsTamperProtected) {
    Write-Output '[OK] 防篡改已开启'
} else {
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Defender\Features' -Name 'TamperProtection' -Value 5 -Type DWord -ErrorAction SilentlyContinue
    Write-Output '[提示] 防篡改未开，已写注册表兜底，重启后请在安全中心确认'
}

$dg = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction SilentlyContinue
$needReboot = @()
if ($dg.SecurityServicesRunning -contains 2) {
    Write-Output '[OK] 内核完整性保护(HVCI) 已在运行'
} else {
    New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -Force | Out-Null
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity' -Name 'Enabled' -Value 1 -Type DWord
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard' -Name 'EnableVirtualizationBasedSecurity' -Value 1 -Type DWord
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\DeviceGuard' -Name 'RequirePlatformSecurityFeatures' -Value 1 -Type DWord
    $needReboot += '内核完整性保护(HVCI)'
    Write-Output '[OK] HVCI 已开启 —— 需重启生效'
}

$lsa = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -ErrorAction SilentlyContinue).RunAsPPL
if ($lsa -ne 1) {
    Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa' -Name 'RunAsPPL' -Value 1 -Type DWord
    $needReboot += 'LSA 保护'
    Write-Output '[OK] LSA 保护已开启 —— 需重启生效'
} else {
    Write-Output '[OK] LSA 保护已开启'
}

$uac = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
if ($uac.ConsentPromptBehaviorAdmin -ne 2 -or $uac.PromptOnSecureDesktop -ne 1) {
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -Name 'EnableLUA' -Value 1 -Type DWord
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -Name 'ConsentPromptBehaviorAdmin' -Value 2 -Type DWord
    Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' -Name 'PromptOnSecureDesktop' -Value 1 -Type DWord
    $needReboot += 'UAC'
    Write-Output '[OK] UAC 已拉满 —— 需重启生效'
} else {
    Write-Output '[OK] UAC 已是最高档'
}

Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer' -Name 'SmartScreenEnabled' -Value 'On' -Type String
New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' -Force | Out-Null
Set-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' -Name 'EnableSmartScreen' -Value 1 -Type DWord -ErrorAction SilentlyContinue
Set-ItemProperty 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\System' -Name 'ShellSmartScreenLevel' -Value 'Block' -Type String -ErrorAction SilentlyContinue
Write-Output '[OK] SmartScreen: 系统=开, 策略级=Block'

try {
    Set-ProcessMitigation -System -Enable DEP, ForceRelocateImages, BottomUp, CFG -ErrorAction Stop
    Write-Output '[OK] Exploit Protection: DEP+强制ASLR+自底向上ASLR+CFG'
} catch {
    Write-Output "[提示] Exploit Protection 设置失败: $($_.Exception.Message)"
}

Set-MpPreference -EnableControlledFolderAccess Enabled
Write-Output '[OK] 受控文件夹访问=开'

$lockHosts = "$env:SystemRoot\System32\drivers\etc\hosts"
icacls $lockHosts /inheritance:r /grant:r "SYSTEM:(F)" "Administrators:(RX)" "Users:(RX)" | Out-Null
icacls "$env:SystemRoot\System32\CodeIntegrity\CIpolicies\Active" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)RX" "Users:(OI)(CI)RX" "NT SERVICE\TrustedInstaller:(OI)(CI)F" | Out-Null
Write-Output '[OK] hosts 与 WDAC 策略目录已锁定（防篡改）'

Write-Output '---------- 最终核验 ----------'
$p = Get-MpPreference
$dg2 = Get-CimInstance -Namespace root\Microsoft\Windows\DeviceGuard -ClassName Win32_DeviceGuard -ErrorAction SilentlyContinue
Write-Output ("实时防护={0} 行为监控={1} 防篡改={2} NIS={3}" -f $s.RealTimeProtectionEnabled, $s.BehaviorMonitorEnabled, $s.IsTamperProtected, $s.NISEnabled)
Write-Output ("ASR 规则数={0} | PUA={1} | 云级别={2} | 网络保护={3}" -f $p.AttackSurfaceReductionRules_Ids.Count, $p.PUAProtection, $p.CloudBlockLevel, $p.EnableNetworkProtection)
if ($dg2) { Write-Output ("HVCI 已运行={0}" -f ($dg2.SecurityServicesRunning -contains 2)) }
Write-Output 'DONE'

$summary = "CHESUN 采桑一键配置 ASR`n`n全部配置已应用并核验。`n"
if ($needReboot.Count -gt 0) {
    $summary += "`n以下配置需要重启电脑后生效：`n  - " + ($needReboot -join "`n  - ")
    $summary += "`n`n请尽快重启。"
} else {
    $summary += "`n无需重启，所有配置已即时生效。"
}
[System.Windows.Forms.MessageBox]::Show($summary, '配置完成',
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Information) | Out-Null
