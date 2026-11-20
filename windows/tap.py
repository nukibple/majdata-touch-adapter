#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tap.py —— 直接给桥接发"点击"(按下-保持-抬起)序列，用来验证游戏是否响应面板数据

用法:
  python3 tap.py --zones C1,C2 --hold 120 --gap 250     # 点中心 120ms
  python3 tap.py --zones A3 --hold 150                  # 点 A3
"""
import argparse
import socket
import time

ROWS = [
    ["A1", "A2", "A3", "A4", "A5"],
    ["A6", "A7", "A8", "B1", "B2"],
    ["B3", "B4", "B5", "B6", "B7"],
    ["B8", "C1", "C2", "D1", "D2"],
    ["D3", "D4", "D5", "D6", "D7"],
    ["D8", "E1", "E2", "E3", "E4"],
    ["E5", "E6", "E7", "E8"],
]


def frame(zones):
    mask = []
    for row in ROWS:
        v = 0
        for j, name in enumerate(row):
            if name in zones:
                v |= (1 << j)
        mask.append(v)
    return bytes([0x28] + mask + [0x29])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.5.2")
    ap.add_argument("--port", type=int, default=23333)
    ap.add_argument("--zones", default="C1,C2")
    ap.add_argument("--hold", type=int, default=120, help="按下保持毫秒")
    ap.add_argument("--gap", type=int, default=250, help="抬起保持毫秒")
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()

    zs = set(x.strip() for x in a.zones.split(",") if x.strip())
    down = frame(zs)
    up = frame(set())
    print(f"点击 {sorted(zs)}: down={down.hex(' ')}  up={up.hex(' ')}")

    s = socket.create_connection((a.host, a.port), timeout=3)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def stream(pkt, ms, hz=100):
        end = time.time() + ms / 1000.0
        period = 1.0 / hz
        while time.time() < end:
            s.sendall(pkt)
            time.sleep(period)

    for i in range(a.repeat):
        stream(up, a.gap)
        stream(down, a.hold)
        stream(up, a.gap)
        print(f"  第 {i+1} 次点击完成")
    s.close()


if __name__ == "__main__":
    main()
