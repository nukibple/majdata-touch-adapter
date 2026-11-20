<#
    monitor.ps1 —— 游戏进程守护 + 收尾
      监视虚拟串口是否被游戏占用，占用了就说明游戏在跑；一旦释放超过 N 秒，
      判定游戏已退出，随即：停桥接/HUD → 把屏幕恢复成启动前的方向。

    用法（由 run.bat 调用）：
      powershell -File monitor.ps1 -Save            # 记录当前屏幕方向，立即返回
      powershell -File monitor.ps1 -Wait            # 阻塞，游戏退出后自动收尾

    只靠串口占用判断，不需要知道任何进程名。
#>
param(
    [switch]$Save,
    [switch]$Wait,
    [string]$Com = "COM1",
    [int]$FreeSeconds = 4,
    [string]$ToolDir = $PSScriptRoot
)

$ErrorActionPreference = "Continue"
$stateFile = Join-Path $env:TEMP "mjdz-screen-state.txt"

function Get-Orientation {
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
    $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    if ($b.Height -gt $b.Width) { "portrait" } else { "landscape" }
}

function Is-ComBusy {
    try {
        $sp = New-Object System.IO.Ports.SerialPort $Com, 9600
        $sp.Open()
        $sp.Close()
        $false
    } catch {
        $true
    }
}

if ($Save) {
    $o = Get-Orientation
    Set-Content -Path $stateFile -Value $o -Encoding ASCII
    Write-Host "  [i] 已记录原屏幕方向: $o"
    exit 0
}

if ($Wait) {
    $orig = "landscape"
    if (Test-Path $stateFile) { $orig = (Get-Content $stateFile -Raw).Trim() }
    Write-Host "  [i] 等待游戏启动（监视 $Com 占用情况）..."
    $seen = $false
    $free = 0
    while ($true) {
        if (Is-ComBusy) {
            if (-not $seen) { Write-Host "  [i] 检测到游戏已占用 $Com，开始守护"; $seen = $true }
            $free = 0
        } else {
            if ($seen) {
                $free++
                if ($free -ge $FreeSeconds) { break }
            }
        }
        Start-Sleep -Seconds 1
    }

    Write-Host "  [i] 游戏已退出，开始收尾..."
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'bridge\.py|hud\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "      已停止 PID $($_.ProcessId)" }
    taskkill /f /fi "WINDOWTITLE eq mjdz-*" >$null 2>&1

    if ($orig -ne (Get-Orientation)) {
        $r = Join-Path $ToolDir "rotate.ps1"
        if (Test-Path $r) {
            & powershell -NoProfile -ExecutionPolicy Bypass -File $r -Orientation $orig | Out-Null
            Write-Host "      屏幕已恢复为 $orig"
        }
    } else {
        Write-Host "      屏幕方向未变（$orig）"
    }
    Write-Host "  [OK] 收尾完成"
    exit 0
}

Write-Host "monitor.ps1: 需要 -Save 或 -Wait"
exit 2
