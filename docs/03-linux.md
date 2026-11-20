# Linux（触屏端）部署

> 实测环境：Surface Pro 5 / Intel i5-7300U / Arch Linux / KDE Plasma 6 (Wayland) /
> linux-surface 内核 `7.3.4-arch1-2-surface` / iptsd 3.1.1 / moonlight-qt 6.2.0

## 1. 依赖

```bash
sudo pacman -S --needed python-evdev python-pillow moonlight-qt
# 可选：调映射用的校准器
sudo pacman -S --needed python-pyqt6
```

## 2. 触摸设备

Surface 的触屏经 `iptsd` 暴露成标准 MT-B 设备：

```bash
python3 panel.py --list | grep -i touch
# /dev/input/event3  IPTSD Virtual Touchscreen 045E:001F
```

* `ABS_MT_POSITION_X 0..9600`、`ABS_MT_POSITION_Y 0..7200`
* 读取需要 `input` 组权限：`sudo usermod -aG input $USER`（重新登录生效）
  —— 或者直接用项目里的 systemd 单元（`User=arch` + `SupplementaryGroups=input`）

## 3. 安装

```bash
sudo install -Dm755 panel.py /usr/local/bin/panel.py
sudo install -Dm644 color_exp_panel.png /usr/share/panel/color_exp_panel.png
sudo install -Dm644 panel.service /etc/systemd/system/panel.service
install -Dm755 setmap.py ~/setmap.py
systemctl --user daemon-reload   # 单元是 system 级，用 sudo systemctl daemon-reload
```

配置 `~/.config/panel/config.json`：

```json
{
  "server": "192.168.5.2",
  "port": 23333,
  "device_name": "IPTSD Virtual Touchscreen",
  "grab": true,
  "screen_w": 1014,
  "screen_h": 1520,
  "rotation": 90,
  "mode": "circle",
  "center": [507.0, 1096.5],
  "radius": 423.5,
  "art": "/usr/share/panel/color_exp_panel.png",
  "scope": 30,
  "points": 12,
  "art_rotation": 0
}
```

* `screen_w/h`：**KWin 的逻辑分辨率**（本例面板 2736×1824、缩放 1.8 → 1520×1014；竖屏后 1014×1520）
* `rotation`：panel 原生坐标 → 逻辑屏幕的旋转，竖屏游玩时是 90 或 270
* `scope`：采样半径（art 583px 坐标系），大了会「一次按压点亮好几个区」
* `grab: true`：独占 `/dev/input/event3`，KWin 就收不到触摸，
  Moonlight 也就不会把触摸当鼠标发给主机（避免双输入）

## 4. 一键脚本

```bash
~/start.sh     # 起 panel + 面板自动隐藏 + 全屏串流
~/stop.sh      # 关串流 + 停 panel（释放触屏独占）
```

## 5. 关键点：屏幕全屏

KDE 下 Moonlight 拿不到全屏，多数是 **窗口规则里有 `fullscreen=false`** 这条在强制禁止全屏：

```bash
grep -n "fullscreen" ~/.config/kwinrulesrc
```

本项目最终使用的规则（`~/.config/kwinrulesrc`）：

```ini
[9]
Description=Moonlight 全屏
fullscreen=true
fullscreenrule=2
noborder=true
noborderrule=2
title=Moonlight
titlematch=2
types=1
```

改完 `qdbus6 org.kde.KWin /KWin reconfigure` 立即生效。

另外把 KDE 面板设为自动隐藏（全屏时不挡画面）：

```bash
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
  'panels().forEach(function(p){ p.hiding = "autohide"; });'
```

## 6. 校准

见 [04-校准.md](04-校准.md)。
