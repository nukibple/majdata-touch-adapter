#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
game_sim.py —— 假游戏：用来在没有 majdata 的情况下验证整条链路

它扮演"游戏"这一端：打开与 bridge 配对的另一个虚拟串口（默认 COM33），
按游戏的方式发握手包，然后解码收到的面板数据包并打印分区名。
玩法：在 Surface 上点触控圆的不同位置，看这里打印的分区是否对得上。

用法：
  python game_sim.py --com COM33            # 常规
  python game_sim.py --com COM33 --raw      # 同时打印原始字节
  python game_sim.py --test-pattern         # 只做一次握手自检后退出
"""

import argparse
import sys
import time

ZONE_ROWS = [
    ["A1", "A2", "A3", "A4", "A5"],
    ["A6", "A7", "A8", "B1", "B2"],
    ["B3", "B4", "B5", "B6", "B7"],
    ["B8", "C1", "C2", "D1", "D2"],
    ["D3", "D4", "D5", "D6", "D7"],
    ["D8", "E1", "E2", "E3", "E4"],
    ["E5", "E6", "E7", "E8"],
]


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def decode(frame):
    out = []
    for i, row in enumerate(ZONE_ROWS):
        v = frame[1 + i]
        for j, name in enumerate(row):
            if v & (1 << j):
                out.append(name)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--com", default="COM33", help="游戏这一端（默认 COM33）")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--raw", action="store_true")
    ap.add_argument("--test-pattern", action="store_true")
    args = ap.parse_args()

    import serial

    try:
        ser = serial.Serial(args.com, args.baud, timeout=0.05)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"打开 {args.com} 失败: {e}\n  → 先建好虚拟串口对（COM3 ↔ COM33）")

    # 1) 模拟游戏的设置握手：发一个 'k' 包，等脚本回写
    ser.write(bytes([40, 0x12, 0x34, ord("k"), 0x56, 41]))
    time.sleep(0.1)
    echo = b""
    for _ in range(20):
        echo += ser.read(16)
        if len(echo) >= 6:
            break
        time.sleep(0.02)
    if echo:
        log("收到脚本回写:", echo[:6].hex(" "), "(应为 28 12 34 6B 56 29)")
    else:
        log("!! 没有收到回写 —— 桥接没在运行，或串口对没配好")

    # 2) 告诉脚本"游戏开始读取"
    ser.write(bytes([40, 0, 0, ord("A"), 0, 41]))
    log("已发送激活指令 'A'，开始接收面板数据包…")

    buf = b""
    last = None
    t0 = time.time()
    frames = 0
    try:
        while True:
            data = ser.read(64)
            if data:
                buf += data
                while len(buf) >= 9:
                    f, buf = buf[:9], buf[9:]
                    if f[0] != 0x28 or f[-1] != 0x29:
                        log("非法帧，重新同步:", f.hex(" "))
                        buf = b""
                        break
                    frames += 1
                    z = decode(f)
                    if z != last:
                        last = z
                        txt = " ".join(z) if z else "-"
                        if args.raw:
                            log(f"帧 {f.hex(' ')} -> {txt}")
                        else:
                            print(f"\r[{(time.time() - t0):6.1f}s] {frames:6d} 帧  按下: {txt:<48}", end="", flush=True)
            if args.test_pattern and time.time() - t0 > 3:
                break
    except KeyboardInterrupt:
        pass
    finally:
        ser.write(bytes([40, 0, 0, ord("L"), 0, 41]))
        ser.close()
        print()
        log(f"共收到 {frames} 帧，已发送停止指令 'L'")


if __name__ == "__main__":
    main()
