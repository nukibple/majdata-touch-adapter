<#
    check.ps1 —— 环境自检（由 一键启动.bat 调用）
    返回 0 = 可以启动；1 = 有阻塞问题（控制台会说明怎么修）
#>
$ErrorActionPreference = "Continue"
$script:fail = 0
function OK($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [警告] $m" -ForegroundColor Yellow }
function Bad($m, $fix) {
    Write-Host "  [失败] $m" -ForegroundColor Red
    if ($fix) { Write-Host "         → $fix" -ForegroundColor Gray }
    $script:fail++
}
$root = (Get-Location).Path
$tool = Join-Path $root "tool"
$pkg  = Join-Path $root "Package"
Write-Host "`n=== 1/6 目录检查 ===" -ForegroundColor Cyan
Write-Host "  当前目录: $root"
if (Test-Path (Join-Path $root "Package")) { OK "找到 Package 目录" }
else { Bad "没有找到 Package 目录" "请把『一键启动.bat』和『tool』文件夹放到游戏根目录（与 Package 同级）" }
$launch = Get-ChildItem $root -Filter "*.bat" | Where-Object { $_.Name -match '^启动|^start' } | Select-Object -First 1
if ($launch) { OK "找到游戏启动脚本: $($launch.Name)" }
else { Bad "没有找到游戏启动脚本（启动.bat）" "确认游戏根目录里有 启动.bat" }
if (Test-Path (Join-Path $tool "bridge.py")) { OK "程序目录 tool 完整" }
else { Bad "tool 文件夹缺失或不完整" "重新解压 release 包，保持『一键启动.bat』与『tool』同级" }
Write-Host "`n=== 2/6 内置 Python ===" -ForegroundColor Cyan
$py = Join-Path $tool "python\python.exe"
if (Test-Path $py) {
    $v = & $py -c "import sys,serial;print(sys.version.split()[0]+' / pyserial '+serial.VERSION)" 2>&1
    if ($LASTEXITCODE -eq 0) { OK "Python $v" }
    else { Bad "内置 Python 无法运行: $v" "解压是否被杀毒软件拦截？重新解压" }
} else { Bad "缺少 tool\python\python.exe" "重新解压 release 包" }
Write-Host "`n=== 3/6 虚拟串口 ===" -ForegroundColor Cyan
$ports = [System.IO.Ports.SerialPort]::GetPortNames()
Write-Host "  当前串口: $($ports -join ', ')"
$need = @("COM1","COM2")
$missing = $need | Where-Object { $ports -notcontains $_ }
if (-not $missing) { OK "COM1 / COM2 都在" }
else {
    Bad "缺少串口: $($missing -join ', ')" `
        "需要用『虚拟串口软件』创建一对互通端口 COM1 与 COM2；`n         重启后端口消失的话，用它自带的驱动管理界面重新启用驱动，或在设备管理器里检查端口设备是否报错"
}
Write-Host "`n=== 4/6 游戏配置 主配置 ini ===" -ForegroundColor Cyan
$ini = Join-Path $pkg "主配置 ini"
if (Test-Path $ini) {
    $bytes = [IO.File]::ReadAllBytes($ini)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $txt = [IO.File]::ReadAllText($ini) -replace "^\uFEFF", ""
        [IO.File]::WriteAllText($ini, $txt, (New-Object System.Text.UTF8Encoding($false)))
        Warn "主配置 ini 带 BOM（会导致 GameDaemon 启动失败），已自动去掉"
    }
    $txt = [IO.File]::ReadAllText($ini)
    if ($txt -match '(?m)^dipsw1\s*=\s*1') {
        $txt = $txt -replace '(?m)^dipsw1\s*=.*$', 'dipsw1=0'
        [IO.File]::WriteAllText($ini, $txt, (New-Object System.Text.UTF8Encoding($false)))
        Warn "dipsw1=1（离线模式）会导致刷不上卡，已自动改为 0"
    }
    if ($txt -match '(?m)^dipsw1\s*=\s*0') { OK "dipsw1=0（在线模式）" }
    if ($txt -match 'AimeDB\s*=\s*(\S+)') { OK "AimeDB = $($Matches[1])" }
} else { Bad "Package\主配置 ini 不存在" "游戏文件不完整？" }
$toml = Join-Path $pkg "mod 配置.toml"
if (Test-Path $toml) {
    $t = [IO.File]::ReadAllText($toml, [Text.Encoding]::GetEncoding(936))
    if ($t -match 'PortName_1P\s*=\s*"([^"]+)"') {
        $pn = $Matches[1]
        if ($pn.Trim().ToUpper() -eq "COM1") { OK "mod 配置 触摸板端口 = COM1" }
        else { Bad "mod 配置 触摸板端口是 $pn，应为 COM1" "把 Package\mod 配置.toml 的 [GameSystem.TouchPanelPort] PortName_1P 改成 `"COM1`"" }
    } else { Warn "mod 配置.toml 里没找到 PortName_1P（可能用默认 COM3）" }
} else { Warn "Package\mod 配置.toml 不存在（需要 mod 配置 mod）" }
Write-Host "`n=== 5/6 串流服务 Sunshine ===" -ForegroundColor Cyan
$sun = Get-Service SunshineService -ErrorAction SilentlyContinue
if ($sun) {
    if ($sun.Status -eq "Running") { OK "SunshineService 正在运行" }
    else { Warn "SunshineService 未运行（本机直玩不影响，串流需要它）" }
} else { Warn "没装 Sunshine 服务（只想本机玩可忽略；串流到平板才需要）" }
Write-Host "`n=== 6/6 屏幕方向 ===" -ForegroundColor Cyan
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
Write-Host "  当前分辨率: $($b.Width)x$($b.Height)"
if ($b.Height -gt $b.Width) { OK "已是竖屏" }
else { Warn "当前是横屏，游戏按 1080x1920 竖屏设计；启动时会尝试自动转竖屏" }
Write-Host ""
if ($script:fail -gt 0) {
    Write-Host "=== 自检未通过（$script:fail 项）===" -ForegroundColor Red
    Write-Host "按上面的 → 提示处理后重新双击『一键启动.bat』。" -ForegroundColor Yellow
    exit 1
}
Write-Host "=== 自检全部通过 ===" -ForegroundColor Green
exit 0
