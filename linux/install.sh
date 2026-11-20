#!/usr/bin/env bash
# install.sh —— Linux/Surface 端：环境检查 + 安装
# 用法:  sudo ./install.sh [--host 192.168.5.2] [--port 23333] [--check]
set -uo pipefail

HOST="192.168.5.2"
PORT="23333"
CHECK_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL=0
WARN=0

ok()   { printf '  \033[32m[OK]\033[0m   %s\n' "$1"; }
warn() { printf '  \033[33m[警告]\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  \033[31m[失败]\033[0m %s\n' "$1"; printf '         → %s\n' "$2"; FAIL=$((FAIL+1)); }

echo
echo "============================================================"
echo "  触屏适配器（majdata） —— 触屏端安装/自检"
echo "  主机: ${HOST}:${PORT}"
echo "============================================================"

echo
echo "=== 1/6 Python 与依赖 ==="
if command -v python3 >/dev/null 2>&1; then
    ok "python3 $(python3 -V 2>&1 | awk '{print $2}')"
else
    bad "没有 python3" "sudo pacman -S python   （Debian/Ubuntu: sudo apt install python3）"
fi

py_check() { python3 - "$1" <<'PY' 2>/dev/null
import importlib, sys
try:
    importlib.import_module(sys.argv[1])
    print("ok")
except Exception:
    print("no")
PY
}

if [ "$(py_check evdev)" = "ok" ]; then ok "python-evdev 已安装"
else bad "缺少 python-evdev（读触屏必需）" "sudo pacman -S python-evdev   /   sudo apt install python3-evdev"; fi

if [ "$(py_check PIL)" = "ok" ]; then ok "Pillow 已安装"
else bad "缺少 Pillow（读分区图必需）" "sudo pacman -S python-pillow   /   sudo apt install python3-pil"; fi

echo
echo "=== 2/6 触屏设备 ==="
TOUCH_LINE=""
if [ "$(py_check evdev)" = "ok" ]; then
    TOUCH_LINE=$(python3 - <<'PY' 2>/dev/null
import evdev
for p in evdev.list_devices():
    d = evdev.InputDevice(p)
    caps = d.capabilities()
    if evdev.ecodes.EV_ABS in caps:
        codes = [c for c, _ in caps[evdev.ecodes.EV_ABS]]
        if evdev.ecodes.ABS_MT_POSITION_X in codes:
            print(f"{p}\t{d.name}")
            break
PY
)
fi
if [ -n "$TOUCH_LINE" ]; then
    ok "触屏: $(echo "$TOUCH_LINE" | cut -f1)  $(echo "$TOUCH_LINE" | cut -f2)"
else
    bad "没有找到多点触控设备（MT-B）" "Surface 需要 iptsd（linux-surface）；其他设备确认内核触摸驱动已加载，且当前用户在 input 组：sudo usermod -aG input \$USER"
fi

echo
echo "=== 3/6 串流客户端 ==="
if command -v moonlight >/dev/null 2>&1; then ok "moonlight 已安装"
else bad "没有 moonlight-qt" "sudo pacman -S moonlight-qt   /   flatpak install flathub com.moonlight_stream.Moonlight"; fi

echo
echo "=== 4/6 与主机的连通性 ==="
if ping -c1 -W2 "$HOST" >/dev/null 2>&1; then
    ok "能 ping 通 $HOST"
else
    bad "ping 不通 $HOST" "确认两台设备在同一网段、主机防火墙放行；或改 --host <主机IP>"
fi
if timeout 3 bash -c "cat < /dev/null > /dev/tcp/$HOST/$PORT" 2>/dev/null; then
    ok "主机桥接端口 $PORT 可连"
else
    warn "主机 $PORT 暂不可连（Windows 端『一键启动.bat』还没运行时会这样，先在主机上启动它）"
fi

echo
echo "=== 5/6 权限 ==="
if id -nG "$USER" 2>/dev/null | tr ' ' '\n' | grep -qx input; then
    ok "用户 $USER 在 input 组"
else
    warn "用户 $USER 不在 input 组（用 systemd 服务运行时无影响）"
fi

if [ "$CHECK_ONLY" = "1" ]; then
    echo
    [ "$FAIL" -eq 0 ] && { echo "=== 自检通过（警告 $WARN 项）==="; exit 0; }
    echo "=== 自检失败 $FAIL 项 ==="; exit 1
fi

[ "$FAIL" -gt 0 ] && { echo; echo "=== 有 $FAIL 项阻塞问题，先按上面提示处理 ==="; exit 1; }

# 需要写 /usr/local、/etc → 非 root 时用 sudo 重跑自己（只问一次密码）
if [ "$(id -u)" -ne 0 ]; then
    echo
    echo "=== 需要管理员权限写入 /usr/local 与 /etc，即将请求 sudo ==="
    exec sudo -E bash "$0" "$@"
fi

# root 下 HOME 会变成 /root，这里取回真实用户的 home
TARGET_HOME="${SUDO_USER:+$(getent passwd "$SUDO_USER" | cut -d: -f6)}"
TARGET_HOME="${TARGET_HOME:-$HOME}"

echo
echo "=== 6/6 安装 ==="

install -Dm755 "$SRC/panel.py" /usr/local/bin/majdata-panel.py
install -Dm644 "$SRC/color_exp_panel.png" /usr/share/majdata-panel/color_exp_panel.png
install -Dm644 "$SRC/panel.service" /etc/systemd/system/panel.service
install -Dm755 "$SRC/setmap.py" "$TARGET_HOME/setmap.py"
install -Dm755 "$SRC/start.sh" "$TARGET_HOME/start.sh"
install -Dm755 "$SRC/stop.sh" "$TARGET_HOME/stop.sh"

# 首次安装生成配置
CFG="$TARGET_HOME/.config/majdata-panel/config.json"
if [ ! -f "$CFG" ]; then
    mkdir -p "$(dirname "$CFG")"
    DEV="${TOUCH_LINE%%$'\t'*}"
    python3 - "$CFG" "$HOST" "$PORT" "$DEV" <<'PY'
import json, sys, subprocess
cfg_path, host, port, dev = sys.argv[1:5]
geo = {"screen_w": 1014, "screen_h": 1520, "center": [507.0, 1096.5], "radius": 423.5}
# 尝试读取当前逻辑分辨率
try:
    out = subprocess.run(["kscreen-doctor","-j"], capture_output=True, text=True, timeout=5).stdout
    import re
    m = re.search(r'"size":\{"width":(\d+),"height":(\d+)\}', out)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        geo["screen_w"], geo["screen_h"] = w, h
except Exception:
    pass
cfg = {
    "server": host, "port": int(port), "device": dev, "grab": True,
    "mode": "circle", "rotation": 90,
    "screen_w": geo["screen_w"], "screen_h": geo["screen_h"],
    "center": geo["center"], "radius": geo["radius"],
    "art": "/usr/share/majdata-panel/color_exp_panel.png",
    "scope": 30, "points": 12, "art_rotation": 0,
}
json.dump(cfg, open(cfg_path, "w"), ensure_ascii=False, indent=2)
print("配置已生成:", cfg_path)
PY
else
    echo "配置已存在，保留: $CFG"
fi

systemctl daemon-reload
echo
echo "=== 安装完成 ==="
echo "  启动: ~/start.sh"
echo "  停止: ~/stop.sh        （会释放触屏独占）"
echo "  微调: python3 ~/setmap.py --cx 540 --cy 1385 --r 535"
echo
echo "下一步：Windows 端把『一键启动.bat』+『majdata-touch』放进游戏根目录并双击。"
