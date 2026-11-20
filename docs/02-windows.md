# Windows 主机部署

> 目标：游戏跑在本机，触摸板数据从 `COM1` 读进来。

## 1. 虚拟串口（功能要求）

游戏读的是串口，桥接也要串口，所以需要**一款能创建"成对互通"虚拟串口的软件**：
往里写什么，另一端就收到什么。

| 必须具备 | 说明 |
|---|---|
| 能建一对端口 | 例如把 `COM1` 与 `COM2` 配成一对 |
| 双向透传 | 写 `COM2` → 游戏从 `COM1` 读到 |
| Win11 可用 | 内核驱动必须在新系统上有有效签名 |

> 买/选哪款不属于本项目范围，只要满足上面三条即可。端口号可按需改，
> 只需同步改 `bridge.py --com` 与 AquaMai 的 `PortName_1P`。

**选型提示**：优先选仍在使用有效签名证书、持续更新的商业/开源驱动；
很多老牌免费虚拟串口工具用的是多年前过期的签名证书，在新版 Windows 上会加载失败
（设备管理器里表现为设备报错、端口消失）。装好后先在设备管理器确认端口正常出现。

约定：**桥接占 `COM2`，游戏占 `COM1`**。

## 2. Sunshine

安装后确认服务运行：

```powershell
Get-Service SunshineService     # 应为 Running
```

串流参数实测可用：`1080x1920@60`、HEVC、50 Mbps、NVENC。

## 3. 游戏配置（`Package\` 目录）

### `主配置文件`

```ini
[AM]
DummyTouchPanel=0
```

### `segatools.ini`

```ini
[vfs]
amfs=amfs
option=option
appdata=appdata

[aime]
enable=1
aimeGen=1

[dns]
enable=1
Default=play.mumur.net
AimeDB=aime.mumur.net

[netenv]
enable=1
addrSuffix=103

[keychip]
enable=1
platformld=ACA1
id=A611-03186083437
subnet=192.168.0.0
gameId=GAMEVER          ; 必须与游戏版本一致
region=4

[system]
enable=1
dipsw1=0             ; ★ 在线模式。=1 不连服务器 → 刷不上卡 / 登录退回
```

> **保存时必须 UTF-8 无 BOM**。带 BOM 会让第一段 `[vfs]` 解析失败，
> GameDaemon 直接 `Vfs: FATAL: AMFS path not specified in INI file` 退出，游戏黑屏。

### `AquaMai.toml`（GBK 编码，别用 UTF-8 覆盖）

```toml
[GameSystem.TouchPanelPort]
PortName_1P = "COM1"      # 默认 COM3，改成桥接对端

[GameSystem.TouchToButtonInput]   # 菜单里分区=按键；长按 C1/C2≥500ms = Select（刷 Aime 卡）

[Utils.DisplayTouchInGame]        # 游戏内触摸可视化，调映射时有用

[GameSystem.Window]
Width = 1080
Height = 1920
```

## 3.5 分区覆盖层（调试开关）

分区状态覆盖层**默认不显示**，只有调试时才打开：

| 方式 | 做法 |
|---|---|
| 临时开 | `一键启动.bat /hud` |
| 长期开/关 | 双击 `分区覆盖层开关.bat`（写 `majdata-touch\hud.ini` 的 `hud=0/1`） |
| 直接改 | `majdata-touch\hud.ini` → `hud=0`(关) / `hud=1`(开) |

覆盖层是**纯 ctypes/GDI 实现，不依赖 tkinter**（内置 Python 没有 tkinter 也能用）：

* 未命中的分区只画细弧线，命中的分区填亮绿 + 顶部显示分区名
* 窗口点击穿透、置顶、`--alpha` 控制整体透明度（默认 0.42）
* 调好映射后保持 `hud=0` 即可，画面干净

## 4. 启动

```powershell
windows\start-all.bat
```

依次：检查 COM1/COM2 → 校验并修正 `dipsw1` → 起桥接（1000 Hz）→ 起 Sunshine 服务 → 起 HUD → 起游戏。

收工：

```powershell
windows\stop-all.bat      # 停游戏/桥接/HUD + 屏幕转回横屏
```

## 5. Aime 卡

* 卡号由 segatools 生成在 `Package\DEVICE\aime.txt`（20 位数字）
* 要在 **MuNET 面板**把这张卡绑定到账号，否则登录会被弹回
* 游戏里长按触摸板圆心（C1/C2 ≥500ms）= Select = 刷这张卡

## 6. 可选：没有游戏时验证链路

```powershell
python bridge.py --com COM2 --port 23333 --mock    # 内置假游戏，无需驱动
python game_sim.py --com COM1                      # 假游戏，验证真实串口对
python tap.py --zones C1,C2 --hold 150 --gap 300      # 直接发一次"点击"
```
