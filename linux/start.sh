#!/usr/bin/env bash
# start.sh —— Surface 侧一键启动：触摸服务 + 面板自动隐藏 + 全屏串流
set -uo pipefail

HOST="${HOST:-192.168.5.2}"
APP="${APP:-majdata DX}"
RES="${RES:-1080x1920}"
FPS="${FPS:-60}"
BITRATE="${BITRATE:-50000}"

export XDG_RUNTIME_DIR=/run/user/1000
export WAYLAND_DISPLAY=wayland-1
export QT_QPA_PLATFORM=wayland

echo "== 1/4 触摸面板服务 =="
sudo systemctl start panel 2>/dev/null
sleep 2
if systemctl is-active --quiet panel; then
  echo "   panel: active (restarts=$(systemctl show panel -p NRestarts --value))"
else
  echo "   [!] panel 没起来，看 journalctl -u panel"
fi

echo "== 2/4 KDE 面板自动隐藏 =="
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
    'panels().forEach(function(p){ p.hiding = "autohide"; });' >/dev/null 2>&1 && echo "   ok"

echo "== 3/4 串流 ${RES}@${FPS} ${BITRATE}kbps -> ${HOST} =="
pkill -x moonlight 2>/dev/null
sleep 1
setsid nohup moonlight stream "$HOST" "$APP" \
      --resolution "$RES" --fps "$FPS" --bitrate "$BITRATE" \
      --display-mode fullscreen > /tmp/moonlight.log 2>&1 < /dev/null &
sleep 6

echo "== 4/4 状态 =="
pgrep -x moonlight >/dev/null && echo "   moonlight: 已启动" || echo "   [!] moonlight 没起来，看 /tmp/moonlight.log"
echo
echo "完成。游戏内如需微调映射:  python3 ~/setmap.py --cy 1380 --r 560"
echo "关闭: ~/stop.sh"
