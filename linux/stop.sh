#!/usr/bin/env bash
# stop.sh —— 关闭串流和触摸服务
export XDG_RUNTIME_DIR=/run/user/1000
pkill -x moonlight 2>/dev/null && echo "moonlight 已关闭"
sudo systemctl stop panel 2>/dev/null && echo "panel 已停止"
echo "（Windows 侧用 stop-all.bat 关闭桥接/HUD/游戏）"
