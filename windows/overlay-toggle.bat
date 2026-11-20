@echo off
chcp 65001 >nul
title 分区覆盖层开关（调试用）
cd /d "%~dp0"
set "INI=%~dp0tool\hud.ini"

if not exist "%INI%" > "%INI%" echo hud=0

set "CUR=0"
for /f "tokens=1,2 delims== " %%a in ('findstr /b /i "hud=" "%INI%"') do set "CUR=%%b"
if "%CUR%"=="1" (set "NEW=0") else (set "NEW=1")
> "%INI%" echo hud=%NEW%

echo ============================================================
if "%NEW%"=="1" (
    echo   分区覆盖层: 已开启 [调试]
    echo   - 下次启动时会在画面上叠一层半透明的分区状态
    echo   - 层内:  F = 只看命中   L = 分区名   Esc = 关闭
    echo   - 调好后双击本文件即可关闭
) else (
    echo   分区覆盖层: 已关闭 [正常游玩]
    echo   - 启动时不再显示，画面干净
)
echo ============================================================
echo   配置: %INI%  -^>  hud=%NEW%
echo.
pause
