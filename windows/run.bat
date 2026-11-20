@echo off
chcp 65001 >nul
title majdata 触屏适配器 - 启动
cd /d "%~dp0"

set "ROOT=%~dp0"
set "TOOL=%~dp0tool"
set "PY=%~dp0tool\python\python.exe"

echo ============================================================
echo    触屏适配器 - 一键启动
echo    触屏端: 在 Linux 设备上运行 start.sh
echo ============================================================

rem ---------- 1. 环境自检 ----------
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOL%\check.ps1"
if errorlevel 1 (
    echo.
    echo [已中止] 环境检查没过，按上面 "->" 提示处理后重试。
    pause
    exit /b 1
)

rem ---------- 2. 记录原屏幕方向 + 分区覆盖层开关 ----------
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOL%\monitor.ps1" -Save -ToolDir "%TOOL%"

set "HUD=0"
if exist "%TOOL%\hud.ini" (
    for /f "tokens=1,2 delims== " %%a in ('findstr /b /i "hud=" "%TOOL%\hud.ini"') do set "HUD=%%b"
)
if /i "%~1"=="/hud" set "HUD=1"

rem ---------- 3. 屏幕转竖屏 ----------
echo.
echo [1/5] 屏幕方向 - 竖屏
powershell -NoProfile -ExecutionPolicy Bypass -File "%TOOL%\rotate.ps1" -Orientation portrait >nul 2>&1
echo      完成

rem ---------- 4. 桥接 ----------
echo.
echo [2/5] 启动桥接  COM2 - TCP 23333
taskkill /f /fi "WINDOWTITLE eq mjdz-bridge*" >nul 2>&1
start "mjdz-bridge" /min cmd /c ""%PY%" "%TOOL%\bridge.py" --com COM2 --port 23333 --hz 1000 --force > "%TOOL%\bridge.log" 2>&1"
ping -n 4 127.0.0.1 >nul
find /i "TCP" "%TOOL%\bridge.log" >nul 2>&1
if errorlevel 1 (echo      [警告] 桥接可能没起来，见 tool\bridge.log) else (echo      桥接已就绪)

rem ---------- 5. 覆盖层（调试用，默认不显示）----------
echo.
echo [3/5] 分区覆盖层  ^(调试用^)
if "%HUD%"=="1" (
    start "mjdz-hud" /min cmd /c ""%PY%" "%TOOL%\hud.py" --game 1080x1920 --alpha 0.42 > "%TOOL%\hud.log" 2>&1"
    echo      已显示 ^(F=只看命中 / L=标签 / 关掉它的窗口即可^)
) else (
    echo      不显示 ^(调好后保持这样^)
    echo      需要调试: 双击『覆盖层开关.bat』，或运行本文件加 /hud
)

rem ---------- 6. 守护（后台）+ 启动游戏 ----------
echo.
echo [4/5] 启动游戏
echo ------------------------------------------------------------
set "GAMEBAT="
if exist "%ROOT%启动.bat"         set "GAMEBAT=%ROOT%启动.bat"
if not defined GAMEBAT if exist "%ROOT%start.bat"         set "GAMEBAT=%ROOT%start.bat"
if not defined GAMEBAT if exist "%ROOT%Package\start.bat" set "GAMEBAT=%ROOT%Package\start.bat"
if not defined GAMEBAT (
    echo [错误] 找不到游戏启动脚本
    pause
    exit /b 1
)

rem 守护进程放到后台：游戏一退出就收尾（停桥接/HUD + 恢复屏幕方向）
start "mjdz-watch" /min cmd /c "powershell -NoProfile -ExecutionPolicy Bypass -File ""%TOOL%\monitor.ps1"" -Wait -ToolDir ""%TOOL%"" >> ""%TOOL%\monitor.log"" 2>&1"

echo 调用: %GAMEBAT%
call "%GAMEBAT%"

echo.
echo [5/5] 等待守护进程收尾（游戏已退出）...
timeout /t 8 >nul
tasklist /fi "WINDOWTITLE eq mjdz-watch*" >nul 2>&1
echo 完成。触屏端记得执行 stop.sh 释放触屏。
ping -n 4 127.0.0.1 >nul
exit /b 0
