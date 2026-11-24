# WinPkgHub 单文件放行 - 验证 / 回滚 工具
# 策略：{5F8B3A85-49C1-4C85-99B7-A265BF83865A}.cip
# 目标基础策略：{E060F2F6-D742-4729-8CDB-C2A1CCB62E07} (SignedReputable_2026-11-22)

param([switch]$Rollback)

$c   = 'C:\Windows\System32\CodeIntegrity\CiPolicies\Active\{5F8B3A85-49C1-4C85-99B7-A265BF83865A}.cip'
$bak = 'C:\Users\18891\WorkBuddy\2026-11-24-18-10-45\WDAC-Active-Backup-2026-11-24'
$exe = 'C:\Users\18891\WorkBuddy\2026-11-24-18-10-45\WinPkgHub\dist\WinPkgHub.exe'

if ($Rollback) {
    if (Test-Path $c) { Remove-Item $c -Force; "已移除放行策略 CIP" } else { "放行策略 CIP 不存在" }
    "重载/重启后失效。备份目录仍在：$bak"
    exit
}

"=== 放行策略状态 ==="
if (Test-Path $c) {
    "已部署：$((Get-Item $c).Length) bytes, sha256=$((Get-FileHash $c).Hash)"
} else { "未部署" }

"=== 最近是否被 WDAC 拦截 ==="
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; StartTime=(Get-Date).AddMinutes(-10)} -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'WinPkgHub' -and $_.Id -in 3077,3033 } |
  Select-Object -First 5 TimeCreated, Id | Format-Table -AutoSize

"=== 启动测试 ==="
try {
    $p = Start-Process -FilePath $exe -PassThru -ErrorAction Stop
    Start-Sleep 4
    $p.Refresh()
    if (-not $p.HasExited) { "放行成功：exe 正在运行 (pid $($p.Id))"; Stop-Process -Id $p.Id -Force }
    else { "exe 启动后退出了 (code $($p.ExitCode))" }
} catch {
    "仍被拦截：$($_.Exception.Message)"
}

"=== 回滚：powershell -File allow-verify.ps1 -Rollback ==="
