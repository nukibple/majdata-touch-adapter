#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bridge.py —— majdata 触控面板 Windows 桥接端

从 TCP 收 panel.py 送来的 9 字节面板数据包，写进虚拟串口（COM3），
游戏从配对的另一个虚拟串口（COM33）读取；同时处理游戏的 6 字节握手包。

协议（与 ERR0RPR0MPT 的两个仓库一致）：
  游戏 -> 脚本：6 字节，data[3] 为 ASCII 命令
      'L'(76) / 'E'(69)  = 游戏停止读取
      'r'(114)/ 'k'(107) = 设置类命令，需回写 bytearray([40, d1,d2,d3,d4, 41])
      'A'(65)            = 游戏开始读取（面板激活）
  脚本 -> 游戏：9 字节  0x28 + 7 字节位掩码 + 0x29

用法：
  python bridge.py --com COM3 --port 23333
  python bridge.py --selftest          # 不需要串口/驱动，离线自检
"""

import argparse
import json
import socket
import sys
import threading
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
FRAME_LEN = 9


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


class Bridge:
    def __init__(self, ser, port=23333, write_hz=200.0, echo=True):
        self.ser = ser
        self.port = port
        self.period = 1.0 / float(write_hz)
        self.echo = echo
        self.frame = bytes([0x28] + [0] * 7 + [0x29])
        self.frame_lock = threading.Lock()
        self.started = False
        self.client = None
        self.clients = 0
        self.running = True
        self.counters = {"in_frames": 0, "out_frames": 0, "cmds": 0}

    # -------------------------------------------------- 串口 -> 游戏状态
    def serial_worker(self):
        buf = b""
        while self.running:
            try:
                data = self.ser.read(64)
            except Exception as e:  # noqa: BLE001
                log("串口读失败:", e)
                time.sleep(0.5)
                continue
            if not data:
                continue
            buf += data
            while len(buf) >= 6:
                pkt, buf = buf[:6], buf[6:]
                self.counters["cmds"] += 1
                c = pkt[3]
                if c in (76, 69):        # 'L' / 'E'
                    if self.started:
                        log("游戏停止读取面板 (0x%02X)" % c)
                    self.started = False
                elif c in (114, 107):    # 'r' / 'k'
                    reply = bytes([40, pkt[1], pkt[2], pkt[3], pkt[4], 41])
                    if self.echo:
                        try:
                            self.ser.write(reply)
                        except Exception as e:  # noqa: BLE001
                            log("回写握手失败:", e)
                    log("握手回写:", reply.hex(" "))
                elif c == 65:            # 'A'
                    if not self.started:
                        log("已连接到游戏，开始输出面板数据")
                    self.started = True
            if len(buf) > 600:          # 防止垃圾数据堆积
                buf = b""

    # -------------------------------------------------- 定时把当前帧写进串口
    def writer_worker(self):
        while self.running:
            if self.started:
                with self.frame_lock:
                    f = self.frame
                try:
                    self.ser.write(f)
                    self.counters["out_frames"] += 1
                except Exception as e:  # noqa: BLE001
                    log("串口写失败:", e)
                    time.sleep(0.2)
            time.sleep(self.period)

    # -------------------------------------------------- TCP 接收面板帧
    def client_worker(self, conn, addr):
        log("Linux 客户端接入:", addr)
        self.clients += 1
        buf = b""
        try:
            while self.running:
                data = conn.recv(256)
                if not data:
                    break
                buf += data
                while len(buf) >= FRAME_LEN:
                    f, buf = buf[:FRAME_LEN], buf[FRAME_LEN:]
                    if f[0] != 0x28 or f[-1] != 0x29:
                        log("丢弃非法帧:", f.hex(" "))
                        buf = b""
                        break
                    with self.frame_lock:
                        self.frame = f
                    self.counters["in_frames"] += 1
        except Exception as e:  # noqa: BLE001
            log("客户端异常:", e)
        finally:
            self.clients -= 1
            self.client = None
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            log("Linux 客户端断开，保持最后一帧")

    def status_server(self, port=23334):
        """给 HUD 用的状态端口：每 100ms 推一行 JSON"""
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", port))
            srv.listen(4)
        except OSError as e:
            log(f"状态端口 {port} 打不开: {e}")
            return
        log(f"状态端口 127.0.0.1:{port} 就绪（给 HUD 用）")
        clients = []

        def pump():
            while self.running:
                with self.frame_lock:
                    f = self.frame
                st = {"t": time.time(), "zones": decode(f), "frame": f.hex(" "),
                      "started": self.started, "in_frames": self.counters["in_frames"]}
                line = (json.dumps(st) + chr(10)).encode()
                for c in list(clients):
                    try:
                        c.sendall(line)
                    except OSError:
                        clients.remove(c)
                time.sleep(0.1)
        threading.Thread(target=pump, daemon=True).start()
        while self.running:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            clients.append(conn)

    def stats_worker(self):
        last_in = 0
        last_out = 0
        while self.running:
            time.sleep(5)
            with self.frame_lock:
                f = self.frame
            dz = decode(f)
            log(f"[stats] 收到帧 {self.counters['in_frames'] - last_in}/5s  "
                f"写串口 {self.counters['out_frames'] - last_out}/5s  "
                f"started={self.started}  当前键={dz if dz else '-'}")
            last_in = self.counters['in_frames']
            last_out = self.counters['out_frames']

    def serve(self, host="0.0.0.0"):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, self.port))
        srv.listen(2)
        log(f"监听 TCP {host}:{self.port}，串口 {getattr(self.ser, 'port', '?')}")
        threading.Thread(target=self.serial_worker, daemon=True).start()
        threading.Thread(target=self.writer_worker, daemon=True).start()
        threading.Thread(target=self.stats_worker, daemon=True).start()
        threading.Thread(target=self.status_server, daemon=True).start()
        try:
            while self.running:
                conn, addr = srv.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.client = conn
                threading.Thread(target=self.client_worker, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            srv.close()

    def stats(self):
        return dict(self.counters, started=self.started, clients=self.clients)


# ---------------------------------------------------------------- 离线自检
class MockSerial:
    """假的游戏端：说同样的协议，记录收到的面板帧"""

    def __init__(self):
        self.rx = b""
        self.tx = b""
        self.received = []
        self.port = "MOCK"
        self.handshook = False

    # 假装游戏 → 脚本 的方向
    def feed_game(self, pkt):
        self.rx += pkt

    def read(self, n):
        if not self.rx:
            time.sleep(0.005)
            return b""
        d, self.rx = self.rx[:n], self.rx[n:]
        return d

    def write(self, data):
        self.tx += data
        if len(data) == FRAME_LEN and data[0] == 0x28:
            self.received.append(data)
        return len(data)


def mock_game(ser, stop_event):
    """--mock 模式：自己扮演游戏，方便没有 majdata 时验证"""
    time.sleep(0.3)
    ser.feed_game(bytes([40, 0x12, 0x34, ord("k"), 0x56, 41]))
    ser.feed_game(bytes([40, 0, 0, ord("A"), 0, 41]))
    shown = 0
    last = None
    while not stop_event.is_set():
        time.sleep(0.05)
        while len(ser.received) > shown:
            f = ser.received[shown]
            shown += 1
            z = decode(f)
            if z != last:
                last = z
                log("  [mock-game] 帧", f.hex(" "), "->", " ".join(z) or "-（无触摸）")

def selftest(port=23399):
    mock = MockSerial()
    br = Bridge(mock, port=port, write_hz=200)
    th = threading.Thread(target=br.serve, kwargs={"host": "127.0.0.1"}, daemon=True)
    th.start()
    time.sleep(0.4)

    # 1) 握手：游戏发 'r' 设置包，桥接要原样回写
    mock.feed_game(bytes([40, 7, 8, ord("r"), 9, 41]))
    time.sleep(0.3)
    assert mock.tx.startswith(bytes([40, 7, 8, ord("r"), 9, 41])), f"握手回写错误: {mock.tx.hex(' ')}"
    print("[ok] 握手回写:", mock.tx[:6].hex(" "))

    # 2) 游戏发 'A' 后应开始持续输出面板帧
    mock.feed_game(bytes([40, 1, 2, ord("A"), 4, 41]))
    time.sleep(0.3)
    assert br.started, "'A' 之后未进入激活状态"
    assert mock.received, "激活后没有输出面板帧"
    zero = mock.received[-1]
    assert set(decode(zero)) == set(), f"默认帧应为空: {decode(zero)}"
    print(f"[ok] 激活后输出 {len(mock.received)} 帧，内容 {zero.hex(' ')}")

    # 3) 从 TCP 推一帧 A1+C2+E8，桥接应把它写进串口
    frame = bytes([0x28, 0x01, 0x00, 0x00, 0x04, 0x00, 0x00, 0x08, 0x29])
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    s.sendall(frame)
    time.sleep(0.35)
    s.close()
    assert frame in mock.received, "TCP 帧没有到达串口"
    assert set(decode(frame)) == {"A1", "C2", "E8"}, decode(frame)
    print("[ok] TCP 帧已写入串口:", frame.hex(" "), "->", decode(frame))

    # 4) 游戏发 'L' 应停止输出
    n_before = len(mock.received)
    mock.feed_game(bytes([40, 0, 0, ord("L"), 0, 41]))
    time.sleep(0.15)
    time.sleep(0.3)
    n_after = len(mock.received)
    assert not br.started, "'L' 之后未停止"
    assert n_after - n_before <= 3, f"'L' 之后仍在输出: {n_after - n_before}"
    print("[ok] 'L' 之后停止输出")

    # 5) 重连再推帧，验证客户端断开后不会崩
    s = socket.create_connection(("127.0.0.1", port), timeout=2)
    mock.feed_game(bytes([40, 0, 0, ord("A"), 0, 41]))
    time.sleep(0.2)
    s.sendall(bytes([0x28, 0, 0, 0, 0, 0, 0, 0, 0x29]))
    time.sleep(0.1)
    s.close()
    time.sleep(0.2)
    print("[ok] 断线重连正常，统计:", br.stats())
    print("\n全部自检通过 ✅")


def main():
    ap = argparse.ArgumentParser(description="majdata 触摸面板 Windows 桥接")
    ap.add_argument("--com", default="COM3", help="脚本占用的一端（默认 COM3）")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--port", type=int, default=23333)
    ap.add_argument("--hz", type=float, default=200.0, help="向串口重复写当前帧的频率")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--no-echo", action="store_true", help="不回写游戏握手包")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--mock", action="store_true", help="用内置假游戏代替真实串口（无需任何驱动）")
    ap.add_argument("--force", action="store_true", help="不等游戏握手，直接持续写帧（调试用）")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    if args.mock:
        m = MockSerial()
        stop = threading.Event()
        bridge = Bridge(m, port=args.port, write_hz=args.hz)
        threading.Thread(target=mock_game, args=(m, stop), daemon=True).start()
        log("mock 模式：不需要串口驱动，等 Linux 端连进来（Ctrl+C 退出）")
        try:
            bridge.serve(args.host)
        finally:
            stop.set()
            log("已退出，统计:", bridge.stats())
        return

    try:
        import serial
    except ImportError:
        sys.exit("缺少 pyserial：python -m pip install pyserial")

    try:
        ser = serial.Serial(args.com, args.baud, timeout=0.02)
    except Exception as e:  # noqa: BLE001
        sys.exit(f"打开 {args.com} 失败: {e}\n"
                 f"  → 需要先用虚拟串口软件建一对互通端口（例如 COM3 <-> COM33），"
                 f"本程序和游戏各占一端。")

    br = Bridge(ser, port=args.port, write_hz=args.hz, echo=not args.no_echo)
    if args.force:
        br.started = True
        log("--force: 无条件输出帧")
    log("起始帧:", br.frame.hex(" "))
    try:
        br.serve(args.host)
    finally:
        try:
            ser.close()
        except Exception:  # noqa: BLE001
            pass
        log("已退出，统计:", br.stats())


if __name__ == "__main__":
    main()
