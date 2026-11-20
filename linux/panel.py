#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
panel.py —— majdata 触控面板客户端 (Linux / Surface 触屏端)

把 Linux 机器（Surface Pro, KDE Wayland + iptsd 虚拟多点触控设备）上的触摸点
换算成 majdata DX 的 34 分区触摸板数据包，经 TCP 送给 Windows 上的 bridge.py，
由它写入虚拟串口，游戏从配对的另一个串口读取。

数据包格式（与 ERR0RPR0MPT/majdata-*-touch-panel 完全一致）:
    0x28 + 7 字节位掩码 + 0x29
    行 0: A1..A5      行 1: A6 A7 A8 B1 B2   行 2: B3..B7
    行 3: B8 C1 C2 D1 D2   行 4: D3..D7      行 5: D8 E1..E4   行 6: E5..E8
    位序: 每行内第一个分区 = bit0 (2**0)

分区判定: 把触摸点按 极坐标 映射回 image/color_exp_panel.png（583x583 的圆形
彩色分区图），取该点及周围一圈点的 RGB，查颜色表得到分区名。该图是官方仓库自带的
分区图，圆形正好内切于图片，因此只需要知道屏幕上的圆心和半径即可，不需要 P 图。

用法:
    python3 panel.py                      # 正常运行（守护）
    python3 panel.py --list                # 列出输入设备
    python3 panel.py --show-touch          # 实时打印触摸点（校准方向用）
    python3 panel.py --calibrate           # 交互校准圆心/半径
    python3 panel.py --selftest            # 离线自检（不出网，不读设备）
    python3 panel.py --inject 760,507      # 用给定屏幕坐标走一遍完整管线
"""

import argparse
import json
import math
import os
import signal
import socket
import sys
import time

# ---------------------------------------------------------------- 常量
ZONE_ROWS = [
    ["A1", "A2", "A3", "A4", "A5"],
    ["A6", "A7", "A8", "B1", "B2"],
    ["B3", "B4", "B5", "B6", "B7"],
    ["B8", "C1", "C2", "D1", "D2"],
    ["D3", "D4", "D5", "D6", "D7"],
    ["D8", "E1", "E2", "E3", "E4"],
    ["E5", "E6", "E7", "E8"],
]

COLOR_MAP = {
    "41-65-93": "A1", "87-152-13": "A2", "213-109-81": "A3", "23-222-55": "A4", "69-203-71": "A5",
    "147-253-55": "A6", "77-19-35": "A7", "159-109-79": "A8", "87-217-111": "B1", "149-95-154": "B2",
    "97-233-9": "B3", "159-27-222": "B4", "152-173-186": "B5", "192-185-149": "B6", "158-45-23": "B7",
    "197-158-219": "B8", "127-144-79": "C1", "242-41-155": "C2", "69-67-213": "D1", "105-25-130": "D2",
    "17-39-170": "D3", "97-103-203": "D4", "113-25-77": "D5", "21-21-140": "D6", "155-179-166": "D7",
    "55-181-134": "D8", "61-33-27": "E1", "51-91-95": "E2", "143-227-63": "E3", "216-67-226": "E4",
    "202-181-245": "E5", "99-11-183": "E6", "75-119-224": "E7", "182-19-85": "E8",
}

DEFAULT_CONFIG = {
    "server": "192.168.5.2",
    "port": 23333,
    "device_name": "IPTSD Virtual Touchscreen",
    "device_path": "",
    "grab": True,
    "screen_w": 1520,
    "screen_h": 1014,
    "rotation": 0,
    "mode": "circle",
    "center": [760.0, 507.0],
    "rect": [0.0, 0.0, 1014.0, 1014.0],
    "radius": 480.0,
    "art": "/usr/share/panel/color_exp_panel.png",
    "scope": 34,
    "points": 8,
    "reverse": False,
    "send_hz": 200,
    "keepalive_ms": 100,
}

CFG_PATH = os.path.expanduser("~/.config/panel/config.json")


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# ---------------------------------------------------------------- 配置
def load_config(path=CFG_PATH):
    cfg = dict(DEFAULT_CONFIG)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:  # noqa: BLE001
            log("配置读取失败，使用默认值:", e)
    return cfg


def save_config(cfg, path=CFG_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    log("配置已写入", path)


# ---------------------------------------------------------------- 分区判定
class ZoneMapper:
    def __init__(self, cfg):
        self.cfg = cfg
        from PIL import Image  # 延迟导入，--list 模式不需要

        self.art = Image.open(cfg["art"]).convert("RGB")
        self.art_w, self.art_h = self.art.size
        self.art_cx = (self.art_w - 1) / 2.0
        self.art_cy = (self.art_h - 1) / 2.0
        self.art_r = self.art_w / 2.0
        self.px = self.art.load()
        self.center = cfg["center"]
        self.radius = float(cfg["radius"])
        self.scope = float(cfg["scope"])
        n = int(cfg["points"])
        self.ring = [
            (math.cos(2 * math.pi * i / n) * self.scope,
             math.sin(2 * math.pi * i / n) * self.scope)
            for i in range(n)
        ]
        self._cache = {}

    def _sample(self, ax, ay):
        ax = int(round(ax))
        ay = int(round(ay))
        if not (0 <= ax < self.art_w and 0 <= ay < self.art_h):
            return None
        key = (ax, ay)
        hit = self._cache.get(key, 0)
        if hit != 0:
            return hit
        r, g, b = self.px[ax, ay]
        name = COLOR_MAP.get(f"{r}-{g}-{b}")
        self._cache[key] = name if name else 1  # 1 = 已知无效
        return name

    def to_art(self, sx, sy):
        """屏幕坐标(逻辑像素) -> 583x583 分区图坐标"""
        if self.cfg.get("mode", "circle") == "rect":
            x0, y0, x1, y1 = self.cfg["rect"]
            ax = (sx - x0) / float(x1 - x0) * (self.art_w - 1)
            ay = (sy - y0) / float(y1 - y0) * (self.art_h - 1)
            return ax, ay
        k = self.art_r / self.radius
        return (self.art_cx + (sx - self.center[0]) * k,
                self.art_cy + (sy - self.center[1]) * k)

    def zones_at(self, sx, sy):
        """屏幕坐标(逻辑像素) -> 分区名集合"""
        ax, ay = self.to_art(sx, sy)
        rot = int(self.cfg.get("art_rotation", 0)) % 360
        if rot:
            dx, dy = ax - self.art_cx, ay - self.art_cy
            for _ in range(rot // 90):
                dx, dy = dy, -dx
            ax, ay = self.art_cx + dx, self.art_cy + dy
        found = set()
        z = self._sample(ax, ay)
        if isinstance(z, str):
            found.add(z)
        for dx, dy in self.ring:
            z = self._sample(ax + dx, ay + dy)
            if isinstance(z, str):
                found.add(z)
        return found


def zones_to_frame(zones):
    mask = []
    for row in ZONE_ROWS:
        v = 0
        for j, name in enumerate(row):
            if name in zones:
                v |= (1 << j)
        mask.append(v)
    return bytes([0x28] + mask + [0x29])


def frame_to_zones(frame):
    """调试用：把数据包还原成分区名"""
    out = []
    for i, row in enumerate(ZONE_ROWS):
        v = frame[1 + i]
        for j, name in enumerate(row):
            if v & (1 << j):
                out.append(name)
    return out


# ---------------------------------------------------------------- evdev 采集
def find_device(cfg):
    import evdev

    if cfg.get("device_path"):
        return evdev.InputDevice(cfg["device_path"])
    want = cfg.get("device_name", "")
    fallback = None
    for path in evdev.list_devices():
        try:
            d = evdev.InputDevice(path)
        except Exception:  # noqa: BLE001
            continue
        if want and want in d.name:
            return d
        if fallback is None and ("Touchscreen" in d.name or "IPTS" in d.name):
            fallback = d
    if fallback:
        return fallback
    raise SystemExit("找不到触摸设备，用 --list 查看可用设备后用 --device /dev/input/eventX 指定")


class TouchReader:
    """Linux 多点触控协议 B (MT-B) 解析"""

    def __init__(self, dev):
        from evdev import ecodes

        self.dev = dev
        self.ecodes = ecodes
        caps = dev.capabilities(absinfo=True)
        absinfo = {c: i for c, i in caps.get(ecodes.EV_ABS, [])}
        self.min_x, self.max_x = 0, 9600
        self.min_y, self.max_y = 0, 7200
        if ecodes.ABS_MT_POSITION_X in absinfo:
            self.min_x, self.max_x = absinfo[ecodes.ABS_MT_POSITION_X].min, absinfo[ecodes.ABS_MT_POSITION_X].max
        if ecodes.ABS_MT_POSITION_Y in absinfo:
            self.min_y, self.max_y = absinfo[ecodes.ABS_MT_POSITION_Y].min, absinfo[ecodes.ABS_MT_POSITION_Y].max
        self.slot = 0
        self.slots = {}

    def normalize(self, raw_x, raw_y):
        nx = (raw_x - self.min_x) / float(self.max_x - self.min_x)
        ny = (raw_y - self.min_y) / float(self.max_y - self.min_y)
        nx = min(1.0, max(0.0, nx))
        ny = min(1.0, max(0.0, ny))
        return nx, ny

    def points(self):
        """返回 [{'nx','ny','x','y'}...]（x/y 为逻辑像素）"""
        cfg = self.cfg
        out = []
        for s in self.slots.values():
            if s.get("id", -1) < 0 or "x" not in s or "y" not in s:
                continue
            nx, ny = self.normalize(s["x"], s["y"])
            out.append({"nx": nx, "ny": ny})
        return out

    def to_screen(self, nx, ny):
        cfg = self.cfg
        rot = int(cfg.get("rotation", 0)) % 360
        if rot == 90:
            nx, ny = ny, 1.0 - nx
        elif rot == 180:
            nx, ny = 1.0 - nx, 1.0 - ny
        elif rot == 270:
            nx, ny = 1.0 - ny, nx
        # 旋转后仍然是"当前屏幕"的宽高（screen_w x screen_h 已经是竖屏值），不要再交换
        w, h = cfg["screen_w"], cfg["screen_h"]
        if cfg.get("reverse"):
            nx, ny = 1.0 - nx, 1.0 - ny
        return nx * w, ny * h

    def feed(self, event):
        ec = self.ecodes
        if event.type == ec.EV_ABS:
            if event.code == ec.ABS_MT_SLOT:
                self.slot = event.value
            elif event.code == ec.ABS_MT_TRACKING_ID:
                if event.value == -1:
                    self.slots.pop(self.slot, None)
                else:
                    self.slots.setdefault(self.slot, {})["id"] = event.value
            elif event.code == ec.ABS_MT_POSITION_X:
                self.slots.setdefault(self.slot, {})["x"] = event.value
            elif event.code == ec.ABS_MT_POSITION_Y:
                self.slots.setdefault(self.slot, {})["y"] = event.value
        return event.type == ec.EV_SYN and event.code == ec.SYN_REPORT


# ---------------------------------------------------------------- TCP
class FrameSender:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.sock = None
        self.last_try = 0.0
        self.connected = False
        self.last_err = ''
        self.last_err_ts = 0.0

    def connect(self, now):
        if self.sock or now - self.last_try < 1.0:
            return
        self.last_try = now
        try:
            s = socket.create_connection((self.host, self.port), timeout=0.5)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock = s
            self.connected = True
            self.last_err = ""
            log(f"已连接 Windows 桥接 {self.host}:{self.port}")
        except OSError as e:
            self.sock = None
            self.connected = False
            msg = str(e)
            if msg != self.last_err or now - self.last_err_ts > 30:
                self.last_err = msg
                self.last_err_ts = now
                log("连接桥接失败(会一直重试):", msg)

    def send(self, frame):
        if not self.sock:
            return
        try:
            self.sock.sendall(frame)
        except OSError as e:
            log("发送失败，断开重连:", e)
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self.connected = False


# ---------------------------------------------------------------- 主循环
def run_touch(cfg, mode="run", inject=None, sender=None, mapper=None):
    if sender is None:
        sender = FrameSender(cfg["server"], cfg["port"])

    if inject is not None:          # 注入模式不碰设备，可在任意机器上验证映射+网络
        sx, sy = inject
        zones = mapper.zones_at(sx, sy)
        frame = zones_to_frame(zones)
        log(f"注入 ({sx:.0f},{sy:.0f}) -> {sorted(zones)}")
        log("数据包:", frame.hex(" "))
        sender.connect(time.monotonic())
        sender.send(frame)
        time.sleep(0.4)
        sender.send(frame)
        time.sleep(0.1)
        return

    dev = find_device(cfg)
    reader = TouchReader(dev)
    reader.cfg = cfg
    log("输入设备:", dev.path, "|", dev.name, f"| ABS_X 0..{reader.max_x} ABS_Y 0..{reader.max_y}")
    if cfg.get("grab") and mode == "run":
        dev.grab()
        log("已独占该设备（KWin 不再收到触摸）")

    import threading

    state = {"frame": b"\x28" + b"\x00" * 7 + b"\x29", "lock": threading.Lock()}
    stop = threading.Event()

    def sender_loop():
        """独立线程按固定频率把当前帧送出去 —— 没触摸时也要保持心跳/重连"""
        hz = max(1.0, float(cfg.get("send_hz", 200)))
        period = 1.0 / hz
        keepalive = cfg.get("keepalive_ms", 100) / 1000.0
        last_sent = b""
        last_ts = 0.0
        while not stop.is_set():
            now = time.monotonic()
            with state["lock"]:
                frame = state["frame"]
            if frame != last_sent or now - last_ts > keepalive:
                sender.connect(now)
                if sender.connected:
                    sender.send(frame)
                    last_sent = frame
                    last_ts = now
                    if os.environ.get("MM_PANEL_DEBUG"):
                        log("frame", frame.hex(" "), frame_to_zones(frame))
            time.sleep(period)

    def state_writer():
        """给 HUD 用的状态文件（/tmp/panel-state.json）"""
        path = "/tmp/panel-state.json"
        last = None
        while not stop.is_set():
            with state["lock"]:
                fr = state["frame"]
                zs = state.get("zones", [])
                pt = state.get("points", [])
            snap = {
                "t": round(time.time(), 3),
                "frame": " ".join(f"{b:02x}" for b in fr),
                "zones": zs,
                "points": pt,
                "connected": bool(sender.connected),
                "geom": {
                    "mode": cfg.get("mode", "circle"),
                    "center": cfg.get("center", [0, 0]),
                    "radius": cfg.get("radius", 1),
                    "rect": cfg.get("rect", [0, 0, 1, 1]),
                    "art_rotation": int(cfg.get("art_rotation", 0)),
                    "screen_w": cfg.get("screen_w", 0),
                    "screen_h": cfg.get("screen_h", 0),
                },
            }
            if snap != last:
                try:
                    with open(path + ".tmp", "w") as f:
                        json.dump(snap, f, ensure_ascii=False)
                    os.replace(path + ".tmp", path)
                except OSError:
                    pass
                last = snap
            time.sleep(0.05)

    threading.Thread(target=state_writer, daemon=True).start()

    if mode != "show":
        threading.Thread(target=sender_loop, daemon=True).start()

    try:
        for event in dev.read_loop():
            if not reader.feed(event):
                continue
            pts = reader.points()
            if mode == "show":
                if not pts:
                    print("\r(无触摸)" + " " * 40, end="", flush=True)
                else:
                    txt = "  ".join(
                        f"({reader.to_screen(p['nx'], p['ny'])[0]:.0f},{reader.to_screen(p['nx'], p['ny'])[1]:.0f})"
                        for p in pts)
                    print("\r触摸点: " + txt + " " * 30, end="", flush=True)
                continue

            try:
                zones = set()
                pts_scr = []
                for p in pts:
                    sx, sy = reader.to_screen(p["nx"], p["ny"])
                    pts_scr.append([round(sx, 1), round(sy, 1)])
                    zones |= mapper.zones_at(sx, sy)
                with state["lock"]:
                    state["frame"] = zones_to_frame(zones)
                    state["zones"] = sorted(zones)
                    state["points"] = pts_scr
            except Exception as e:
                log("处理触摸出错（已忽略）:", e)
                continue
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        stop.set()
        try:
            dev.ungrab()
        except Exception:  # noqa: BLE001
            pass
        dev.close()
        log("已退出")


# ---------------------------------------------------------------- 校准
def calibrate(cfg):
    """依次点圆的最左、最右、最上三个点，自动算圆心与半径"""
    dev = find_device(cfg)
    reader = TouchReader(dev)
    reader.cfg = cfg
    log("校准开始：依次点击触摸圆边缘的 最左 / 最右 / 最上 三个点（每个点按住再抬起）")

    need = ["最左边缘", "最右边缘", "最上边缘"]
    got = []
    tip = 0
    print(f"\n>>> 请点击: {need[tip]}", flush=True)
    for event in dev.read_loop():
        if not reader.feed(event):
            continue
        pts = reader.points()
        if pts:  # 有手指按下，取第一个点
            sx, sy = reader.to_screen(pts[0]["nx"], pts[0]["ny"])
            got.append((sx, sy))
            log(f"记录 {need[len(got) - 1]}: ({sx:.0f}, {sy:.0f})")
            if len(got) == 3:
                break
            print(f">>> 请点击: {need[len(got)]}", flush=True)
    dev.close()

    (lx, ly), (rx, ry), (tx, ty) = got
    cx = (lx + rx) / 2.0
    cy = (ly + ry) / 2.0
    r = math.hypot(rx - lx, ry - ly) / 2.0
    # 上下方向抽检
    r_top = math.hypot(tx - cx, ty - cy)
    log(f"圆心=({cx:.0f},{cy:.0f}) 半径={r:.0f}  上边缘实测半径={r_top:.0f}")
    if abs(r_top - r) > max(12, r * 0.06):
        log("警告: 上下半径与左右半径差得较多，可能是点偏了或屏幕被缩放，建议重校准")
    cfg["center"] = [round(cx, 1), round(cy, 1)]
    cfg["radius"] = round(r, 1)
    save_config({k: cfg[k] for k in ("center", "radius")} | {
        k: v for k, v in cfg.items() if k not in ("center", "radius")})
    log("校准完成")



def calibrate_rect(cfg):
    """点触摸区域的最左上角 + 最右下角，得到屏幕上的方形区域（能同时吃掉 letterbox / 非等比缩放）"""
    dev = find_device(cfg)
    reader = TouchReader(dev)
    reader.cfg = cfg
    log("矩形校准：先点触摸区域的最左上角，再点最右下角")
    need = ["最左上角", "最右下角"]
    got = []
    print(f"\n>>> 请点击: {need[0]}", flush=True)
    for event in dev.read_loop():
        if not reader.feed(event):
            continue
        pts = reader.points()
        if pts:
            sx, sy = reader.to_screen(pts[0]["nx"], pts[0]["ny"])
            got.append((sx, sy))
            log(f"记录 {need[len(got) - 1]}: ({sx:.0f}, {sy:.0f})")
            if len(got) == 2:
                break
            print(f">>> 请点击: {need[1]}", flush=True)
    dev.close()
    (x0, y0), (x1, y1) = got
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    cfg["mode"] = "rect"
    cfg["rect"] = [round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)]
    cfg["center"] = [round((x0 + x1) / 2, 1), round((y0 + y1) / 2, 1)]
    cfg["radius"] = round(min(x1 - x0, y1 - y0) / 2, 1)
    save_config(cfg)
    log(f"矩形={cfg['rect']} 宽={x1-x0:.0f} 高={y1-y0:.0f}")
    log("校准完成（mode=rect）。用 --selftest 或 game_sim.py 验证")

# ---------------------------------------------------------------- 自检
def selftest(cfg):
    mapper = ZoneMapper(cfg)
    cx, cy = cfg["center"]
    r = float(cfg["radius"])
    print(f"圆心 {cx},{cy} 半径 {r:.0f}  scope={cfg['scope']} points={cfg['points']}")
    print("沿半径 4 档 x 8 方位采样：")
    names = ["上", "右上", "右", "右下", "下", "左下", "左", "左上"]
    for frac in (0.95, 0.75, 0.55, 0.35):
        row = []
        for i in range(8):
            ang = -math.pi / 2 + i * math.pi / 4
            sx = cx + math.cos(ang) * r * frac
            sy = cy + math.sin(ang) * r * frac
            z = mapper.zones_at(sx, sy)
            row.append(("/".join(sorted(z)) if z else "-"))
        print(f"  r={frac:4.2f} " + " | ".join(f"{n}:{v:<6}" for n, v in zip(names, row)))
    print("\n中心点:", sorted(mapper.zones_at(cx, cy)))
    print("画面四角(应为空):", sorted(mapper.zones_at(0, 0)), sorted(mapper.zones_at(cfg["screen_w"], cfg["screen_h"])))
    # 帧编解码自检
    f = zones_to_frame({"A1", "C2", "E8"})
    assert f[0] == 0x28 and f[-1] == 0x29, "帧头帧尾错误"
    assert set(frame_to_zones(f)) == {"A1", "C2", "E8"}, f"编解码不一致: {frame_to_zones(f)}"
    print("帧编解码自检通过:", f.hex(" "))


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description="majdata 触摸面板 Linux 客户端")
    ap.add_argument("--config", default=CFG_PATH)
    ap.add_argument("--server")
    ap.add_argument("--port", type=int)
    ap.add_argument("--device", help="输入设备路径, 如 /dev/input/event3")
    ap.add_argument("--screen", help="逻辑分辨率 WxH, 如 1520x1014")
    ap.add_argument("--rotation", type=int, choices=[0, 90, 180, 270])
    ap.add_argument("--center", help="圆心 x,y")
    ap.add_argument("--radius", type=float)
    ap.add_argument("--art")
    ap.add_argument("--scope", type=float)
    ap.add_argument("--list", action="store_true", help="列出输入设备")
    ap.add_argument("--show-touch", action="store_true", help="实时打印触摸坐标")
    ap.add_argument("--calibrate", action="store_true", help="圆形校准：点最左/最右/最上")
    ap.add_argument("--calibrate-rect", action="store_true", help="矩形校准：点最左上/最右下（推荐）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--inject", help="注入一个屏幕坐标 x,y 走完整管线")
    ap.add_argument("--no-grab", action="store_true")
    args = ap.parse_args()

    if args.list:
        import evdev

        for p in evdev.list_devices():
            d = evdev.InputDevice(p)
            print(f"{p}\t{d.name}\t{d.phys}")
        return

    cfg = load_config(args.config)
    if args.server:
        cfg["server"] = args.server
    if args.port:
        cfg["port"] = args.port
    if args.device:
        cfg["device_path"] = args.device
    if args.screen:
        w, h = args.screen.lower().split("x")
        cfg["screen_w"], cfg["screen_h"] = int(w), int(h)
    if args.rotation is not None:
        cfg["rotation"] = args.rotation
    if args.center:
        x, y = args.center.split(",")
        cfg["center"] = [float(x), float(y)]
    if args.radius:
        cfg["radius"] = args.radius
    if args.art:
        cfg["art"] = args.art
    if args.scope:
        cfg["scope"] = args.scope
    if args.no_grab:
        cfg["grab"] = False

    if args.selftest:
        selftest(cfg)
        return
    if args.calibrate:
        calibrate(cfg)
        return

    mapper = ZoneMapper(cfg)
    if args.inject:
        x, y = args.inject.split(",")
        run_touch(cfg, inject=(float(x), float(y)), mapper=mapper)
        return

    log(f"屏幕 {cfg['screen_w']}x{cfg['screen_h']} 旋转 {cfg['rotation']}° 圆心 {cfg['center']} 半径 {cfg['radius']:.0f}")
    log(f"目标 {cfg['server']}:{cfg['port']}")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    run_touch(cfg, mode="show" if args.show_touch else "run", mapper=mapper)


if __name__ == "__main__":
    main()
