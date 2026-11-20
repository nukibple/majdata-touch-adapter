# 故障排查（全是实测踩出来的）

## 一、游戏 / 服务器

### 刷不上卡、登录后被弹回

`segatools.ini` 里 `[system] dipsw1` 必须是 **0**（在线模式）。
`=1` 是独立/机台服务器模式，**不连服务器**，读卡校验必然失败。

验证游戏是否真的连上服务器：

```powershell
$pids = (Get-Process GameApp,GameDaemon).Id
Get-NetTCPConnection | Where-Object { $pids -contains $_.OwningProcess } |
  Select-Object State,RemoteAddress,RemotePort
# 期望看到类似 110.40.128.13:84  (MuNET ALL.Net 端口)
```

### 游戏黑屏 + “你的 GameDaemon 还活着吗？”

先看 GameDaemon 有没有真的起来：

```powershell
Get-Process GameDaemon
cd "…\Package"; inject -d -k gamehook.dll GameDaemon.exe -f -c config_common.json config_server.json
```

如果输出 `Vfs: FATAL: AMFS path not specified in INI file` →
**`segatools.ini` 被写入了 BOM**。用 UTF-8 **无 BOM** 重写：

```powershell
$p = "…\Package\segatools.ini"
$t = [IO.File]::ReadAllText($p) -replace "^\uFEFF", ""
[IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($false)))
```

（PowerShell 的 `Set-Content -Encoding UTF8` 会加 BOM，改 ini 一律用上面的写法）

### 卡号在哪 / 怎么换卡

`Package\DEVICE\aime.txt`，20 位数字，segatools（`aimeGen=1`）生成。
删掉它重启游戏会重新生成。要在 MuNET 面板把卡号绑定到账号。

## 二、串口 / 触摸链路

### 重启后 COM1-COM4 全部消失（`CM_PROB_PHANTOM`）

虚拟串口软件的内核驱动没启动。用该软件自带的驱动管理界面重新启用（或管理员重启其驱动服务），
然后在设备管理器确认端口重新出现。

### 桥接报 `打开 COM2 失败`

同上——端口不存在。先起驱动，再确认 `COM1 ⇄ COM2` 这对还在。

### 触摸没反应，但 HUD 显示“无触摸”

看 `panel` 有没有活着：

```bash
systemctl status panel
systemctl show panel -p NRestarts    # 一直涨 = 崩溃重启循环
journalctl -u panel -n 50 --no-pager
```

### 双输入（鼠标圈 + 分区同时响应）

`panel` 崩溃重启时会释放触屏独占，那一瞬间触摸漏给 KWin，Moonlight 就当鼠标发回主机。
根治就是上面那条：让它别崩（`NRestarts` 保持 0）。

## 三、分区 / 映射

### 位置整体偏移 / 大小不对

用 `setmap.py` 现场调，配合 HUD 观察：

```bash
python3 ~/setmap.py --cx 540 --cy 1385 --r 535
```

### 一按就点亮 2-3 个相邻区

`scope` 太大，调小：`{"scope": 24}`（`~/.config/panel/config.json`）后
`sudo systemctl restart panel`。

### 扇区整体转了一个角度

`--art-rot 90/180/270`。

### 方向完全反了（上下左右颠倒）

`rotation` 差 180°：`--rot 90` ↔ `--rot 270`。

## 四、串流

### Moonlight 全屏不进 / 有标题栏

KDE 窗口规则里有 `fullscreen=false` 在强制禁止全屏：

```bash
grep -n fullscreen ~/.config/kwinrulesrc
```

删掉那两行，或按 [03-Linux.md](03-Linux.md) §5 加一条针对 Moonlight 的放行规则。

### 画面糊 / 比例不对

* Moonlight 侧固定 `--resolution 1080x1920`
* 主机侧 `AquaMai.toml` 的 `[GameSystem.Window] Width/Height` 设为 1080/1920
* 主机屏幕旋转成竖屏（`rotate.ps1 -Orientation portrait`）

## 五、性能参考

实测（Surface Pro 5 + i5-7300U，802.11ac）：

| 项 | 值 |
|---|---|
| TCP 下行（主机→Surface） | 526 Mbps |
| 10 分钟 soak | 平均 519.8 Mbps，0 次卡死，38.98 GB |
| UDP 150 Mbps | 0% 丢包，抖动 0.07 ms |
| 串流 | 1080×1920@60 HEVC，CPU ≈ 15%（VAAPI 硬解） |
