#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setmap.py —— 快速调整分区映射（自动换算 + 重启 panel + 同步 HUD）

参数都用"主机游戏画面 1080x1920"里的坐标，脚本自动换算成 Surface 逻辑坐标。

用法:
  python3 ~/setmap.py                      # 看当前值
  python3 ~/setmap.py --rot 90             # 只改旋转
  python3 ~/setmap.py --cx 540 --cy 1362 --r 548
"""
import argparse
import json
import os
import subprocess
import sys

CFG = os.path.expanduser("~/.config/panel/config.json")
K = 1520.0 / 1920.0
X0 = (1014.0 - 1080.0 * K) / 2.0


def load():
    return json.load(open(CFG))


def show(c):
    cx, cy = c.get("center", [0, 0])
    r = c.get("radius", 0)
    print(f"当前: rotation={c.get('rotation')}  center=({cx:.1f},{cy:.1f})  radius={r:.1f}"
          f"   [换算回主机: cx={(cx - X0) / K:.0f} cy={cy / K:.0f} r={r / K:.0f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rot", type=int, choices=[0, 90, 180, 270])
    ap.add_argument("--cx", type=float)
    ap.add_argument("--cy", type=float)
    ap.add_argument("--r", type=float)
    ap.add_argument("--art-rot", type=int, choices=[0, 90, 180, 270])
    ap.add_argument("--no-restart", action="store_true")
    a = ap.parse_args()

    c = load()
    show(c)

    changed = False
    if a.rot is not None:
        c["rotation"] = a.rot
        changed = True
    if a.art_rot is not None:
        c["art_rotation"] = a.art_rot
        changed = True
    if a.cx is not None or a.cy is not None or a.r is not None:
        cx, cy = c.get("center", [507.0, 1078.0])
        r = c.get("radius", 434.0)
        if a.cx is not None:
            cx = X0 + a.cx * K
        if a.cy is not None:
            cy = a.cy * K
        if a.r is not None:
            r = a.r * K
        c["mode"] = "circle"
        c["center"] = [round(cx, 1), round(cy, 1)]
        c["radius"] = round(r, 1)
        changed = True

    if changed:
        c["screen_w"], c["screen_h"] = 1014, 1520
        json.dump(c, open(CFG, "w"), ensure_ascii=False, indent=2)
        show(c)
        if not a.no_restart:
            subprocess.run(["sudo", "systemctl", "restart", "panel"], check=False)
            print("panel 已重启")
    else:
        print("没改任何参数（用 --help 看用法）")


if __name__ == "__main__":
    main()
