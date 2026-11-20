#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hud.py —— 分区触发状态覆盖层（纯 ctypes/GDI 实现，不需要 tkinter）

从 bridge 的状态端口（TCP 23334）读实时分区，画在游戏画面上：
  · 未命中的分区只画细弧线
  · 手指按到的分区填充亮绿，顶部显示分区名
  · 黑色被设为透明色，其余按 --alpha 整体半透明；窗口点击穿透

用法:
  python hud.py [--host 127.0.0.1] [--port 23334]
                    [--game 1080x1920] [--alpha 0.42]
                    [--cx 540 --cy 1385 --r 535]   # 触摸圆（游戏画面像素）
快捷键（窗口激活时）: F 只看命中   Esc 退出；也可以直接 taskkill
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import math
import socket
import sys
import threading
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t

# ctypes.wintypes 没有 WNDCLASSW，自己定义
class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

# ---- 声明 64 位原型，避免 LPARAM/HDC 被截断 ----
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = wt.WORD
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, wt.BYTE, wt.DWORD]
user32.SetLayeredWindowAttributes.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.UpdateWindow.argtypes = [wt.HWND]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.GetDC.argtypes = [wt.HWND]; user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.FillRect.argtypes = [wt.HDC, ctypes.c_void_p, wt.HBRUSH]
user32.DestroyWindow.argtypes = [wt.HWND]
user32.GetMessageW.argtypes = [ctypes.c_void_p, wt.HWND, wt.UINT, wt.UINT]
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = LRESULT
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]; gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HANDLE]; gdi32.SelectObject.restype = wt.HANDLE
gdi32.CreateSolidBrush.argtypes = [wt.DWORD]; gdi32.CreateSolidBrush.restype = wt.HBRUSH
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wt.DWORD]; gdi32.CreatePen.restype = wt.HPEN
gdi32.DeleteObject.argtypes = [wt.HANDLE]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.Polygon.argtypes = [wt.HDC, ctypes.c_void_p, ctypes.c_int]
gdi32.MoveToEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
gdi32.LineTo.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SetBkMode.argtypes = [wt.HDC, ctypes.c_int]
gdi32.SetTextColor.argtypes = [wt.HDC, wt.DWORD]
gdi32.TextOutW.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int]
gdi32.CreateFontW.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD,
                              wt.DWORD, wt.DWORD, wt.DWORD, wt.LPCWSTR]
gdi32.CreateFontW.restype = wt.HFONT
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]; kernel32.GetModuleHandleW.restype = wt.HMODULE
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002
WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_KEYDOWN = 0x0100
VK_ESCAPE = 0x1B
VK_F = 0x46

COLOR_MAP = {
    "41-65-93": "A1", "87-152-13": "A2", "213-109-81": "A3", "23-222-55": "A4", "69-203-71": "A5",
    "147-253-55": "A6", "77-19-35": "A7", "159-109-79": "A8", "87-217-111": "B1", "149-95-154": "B2",
    "97-233-9": "B3", "159-27-222": "B4", "152-173-186": "B5", "192-185-149": "B6", "158-45-23": "B7",
    "197-158-219": "B8", "127-144-79": "C1", "242-41-155": "C2", "69-67-213": "D1", "105-25-130": "D2",
    "17-39-170": "D3", "97-103-203": "D4", "113-25-77": "D5", "21-21-140": "D6", "155-179-166": "D7",
    "55-181-134": "D8", "61-33-27": "E1", "51-91-95": "E2", "143-227-63": "E3", "216-67-226": "E4",
    "202-181-245": "E5", "99-11-183": "E6", "75-119-224": "E7", "182-19-85": "E8",
}


def zone_polar_shapes(art_path):
    """优先读预计算的 zones_polar.json；没有 PIL 也能运行"""
    import os
    j = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zones_polar.json")
    if os.path.exists(j):
        with open(j) as f:
            return {k: tuple(v) for k, v in json.load(f).items()}
    from PIL import Image
    img = Image.open(art_path).convert("RGB")
    w, h = img.size
    px = img.load()
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    R = w / 2.0
    acc = {}
    for y in range(0, h, 2):
        for x in range(0, w, 2):
            n = COLOR_MAP.get("%d-%d-%d" % px[x, y])
            if not n:
                continue
            dx, dy = x - cx, y - cy
            rad = math.hypot(dx, dy) / R
            ang = math.atan2(dy, dx)
            a = acc.setdefault(n, [1e9, -1e9, [], 0])
            a[0] = min(a[0], rad)
            a[1] = max(a[1], rad)
            a[2].append(ang)
            a[3] += 1
    shapes = {}
    for n, (r0, r1, angs, _c) in acc.items():
        angs.sort()
        gaps = [(angs[(i + 1) % len(angs)] - angs[i], i) for i in range(len(angs))]
        gaps[-1] = (angs[0] + 2 * math.pi - angs[-1], len(angs) - 1)
        _g, gi = max(gaps)
        a0 = angs[(gi + 1) % len(angs)]
        a1 = angs[gi]
        if a1 < a0:
            a1 += 2 * math.pi
        shapes[n] = (r0, r1, a0, a1)
    return shapes


class Hud:
    def __init__(self, host, port, gw, gh, alpha, cx, cy, r, art):
        self.gw, self.gh = gw, gh
        self.alpha = alpha
        self.cx, self.cy, self.r = cx, cy, r
        self.shapes = zone_polar_shapes(art)
        self.zones = set()
        self.stale = True
        self.only_touch = False
        self.host, self.port = host, port
        self._wndproc_ref = WNDPROC(self._wndproc)

        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = "MjdzHudClass"
        wc.hbrBackground = gdi32.CreateSolidBrush(0x000000)
        user32.RegisterClassW(ctypes.byref(wc))

        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW,
            "MjdzHudClass", "mjdz-hud", WS_POPUP | WS_VISIBLE,
            0, 0, gw, gh, None, None, hinst, None)
        if not self.hwnd:
            raise SystemExit("创建窗口失败: %d" % ctypes.get_last_error())

        # 黑色当透明色 + 整体 alpha
        user32.SetLayeredWindowAttributes(self.hwnd, 0x00000000,
                                         int(255 * max(0.05, min(1.0, alpha))),
                                         LWA_COLORKEY | LWA_ALPHA)
        user32.ShowWindow(self.hwnd, 5)          # SW_SHOW
        user32.UpdateWindow(self.hwnd)

        threading.Thread(target=self._net_loop, daemon=True).start()
        user32.SetTimer(self.hwnd, 1, 40, None)  # 25fps

    # ---------------------------------------------------------------- 网络
    def _net_loop(self):
        while True:
            try:
                s = socket.create_connection((self.host, self.port), timeout=2)
                buf = b""
                while True:
                    d = s.recv(4096)
                    if not d:
                        break
                    buf += d
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        try:
                            st = json.loads(line.decode() or "{}")
                        except Exception:
                            continue
                        self.zones = set(st.get("zones") or [])
                        self.stale = False
                s.close()
            except Exception:
                self.stale = True
                time.sleep(1)

    # ---------------------------------------------------------------- GDI 绘制
    def _fill_poly(self, hdc, pts, color):
        brush = gdi32.CreateSolidBrush(color)
        old = gdi32.SelectObject(hdc, brush)
        arr = (wt.POINT * len(pts))(*[wt.POINT(int(x), int(y)) for x, y in pts])
        gdi32.Polygon(hdc, arr, len(pts))
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(brush)

    def _line(self, hdc, x1, y1, x2, y2, color, width=2):
        pen = gdi32.CreatePen(0, width, color)
        old = gdi32.SelectObject(hdc, pen)
        gdi32.MoveToEx(hdc, int(x1), int(y1), None)
        gdi32.LineTo(hdc, int(x2), int(y2))
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(pen)

    def _text(self, hdc, x, y, s, color, size=22, bold=True):
        h = gdi32.CreateFontW(-size, 0, 0, 0, 700 if bold else 400, 0, 0, 0,
                              134, 0, 0, 0, 0, "Microsoft YaHei")
        old = gdi32.SelectObject(hdc, h)
        gdi32.SetBkMode(hdc, 1)                 # TRANSPARENT
        gdi32.SetTextColor(hdc, color)
        gdi32.TextOutW(hdc, int(x), int(y), s, len(s))
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(h)

    def _paint(self):
        hdc_win = user32.GetDC(self.hwnd)
        hdc = hdc_win

        # 背景纯黑 = 透明色
        gdi32.CreateSolidBrush(0x000000)
        bg = gdi32.CreateSolidBrush(0x000000)
        rc = wt.RECT(0, 0, self.gw, self.gh)
        user32.FillRect(hdc, ctypes.byref(rc), bg)
        gdi32.DeleteObject(bg)

        cx, cy, R = float(self.cx), float(self.cy), float(self.r)
        for name, (r0, r1, a0, a1) in self.shapes.items():
            touched = name in self.zones
            if not touched and self.stale:
                continue
            steps = 10
            if touched:
                pts = []
                for i in range(steps + 1):
                    a = a0 + (a1 - a0) * i / steps
                    pts.append((cx + math.cos(a) * r0 * R, cy + math.sin(a) * r0 * R))
                for i in range(steps + 1):
                    a = a1 - (a1 - a0) * i / steps
                    pts.append((cx + math.cos(a) * r1 * R, cy + math.sin(a) * r1 * R))
                self._fill_poly(hdc, pts, 0x0066FF00)      # GDI 是 BGR: 00 FF 66
            else:
                px = py = None
                for i in range(steps + 1):
                    a = a0 + (a1 - a0) * i / steps
                    x, y = cx + math.cos(a) * r1 * R, cy + math.sin(a) * r1 * R
                    if px is not None:
                        self._line(hdc, px, py, x, y, 0x004F4F1F, 2)
                    px, py = x, y

        # 中心十字
        self._line(hdc, cx - 18, cy, cx + 18, cy, 0x004444FF, 2)
        self._line(hdc, cx, cy - 18, cx, cy + 18, 0x004444FF, 2)

        # 顶部状态条
        bar = wt.RECT(0, 0, self.gw, 52)
        bb = gdi32.CreateSolidBrush(0x002A2A2A)
        user32.FillRect(hdc, ctypes.byref(bar), bb)
        gdi32.DeleteObject(bb)
        if self.stale:
            txt = "HUD: 未连上桥接状态端口 %d" % self.port
        else:
            txt = "命中: " + (" ".join(sorted(self.zones)) if self.zones else "无触摸")
        self._text(hdc, 24, 12, txt, 0x00FFFFE8, 24)

        if self.zones:
            self._text(hdc, 24, self.gh - 70, "   ".join(sorted(self.zones)), 0x0066FF00, 40)

        user32.ReleaseDC(self.hwnd, hdc_win)

    # ---------------------------------------------------------------- 消息循环
    def _wndproc(self, hwnd, msg, wp, lp):
        if msg == WM_TIMER:
            self._paint()
            return 0
        if msg == WM_KEYDOWN:
            if wp == VK_ESCAPE:
                user32.DestroyWindow(hwnd)
            elif wp == VK_F:
                self.only_touch = not self.only_touch
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def run(self):
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=23334)
    ap.add_argument("--game", default="1080x1920")
    ap.add_argument("--alpha", type=float, default=0.42)
    ap.add_argument("--cx", type=float, default=540)
    ap.add_argument("--cy", type=float, default=1385)
    ap.add_argument("--r", type=float, default=535)
    ap.add_argument("--art", default="")
    a = ap.parse_args()
    gw, gh = (int(v) for v in a.game.lower().split("x"))
    Hud(a.host, a.port, gw, gh, a.alpha, a.cx, a.cy, a.r, a.art).run()


if __name__ == "__main__":
    main()
