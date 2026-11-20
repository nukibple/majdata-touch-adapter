# 致谢

本项目的思路、协议与分区数据来自下面这些项目。
本项目只做了「更换取点端 + 更换传输方式」这一层适配，协议细节严格对齐上游。

## 协议与分区数据

| 项目 | 许可 | 本项目的使用 |
|---|---|---|
| [ERR0RPR0MPT/上游触屏实现](https://github.com/ERR0RPR0MPT/上游触屏实现) | MIT | 9 字节帧格式、34 分区表、分区颜色表、握手字节语义、分区彩图素材（`color_exp_panel.png`） |
| [ERR0RPR0MPT/majdata-windows-touch-panel](https://github.com/ERR0RPR0MPT/majdata-windows-touch-panel) | MIT | 串口侧实现参考（读 6 字节 / 回写设置包 / 刷帧节奏）、虚拟串口双端配对的部署范式 |

> 上面两个仓库名里含有游戏名，仅为保留可追溯的原始出处与许可要求；
> 本项目不包含、不分发任何游戏文件。

## 运行环境

| 项目 | 在本项目中的角色 |
|---|---|
| [Sunshine](https://github.com/LizardByte/Sunshine) | 主机端串流（低延迟编码） |
| [moonlight-qt](https://github.com/moonlight-stream/moonlight-qt) | 终端串流客户端（硬解、全屏） |
| [MuNET-OSS/AquaMai](https://github.com/MuNET-OSS/AquaMai) | 游戏侧 mod 框架：触摸板端口配置、触摸转按键、游戏内触摸可视化 |
| [iptsd](https://github.com/linux-surface/iptsd) | 平板触屏驱动，暴露标准多点触控设备 |
| python-evdev · Pillow · pyserial · PyQt6 | 取点、图像、串口、校准工具 |

## 与本项目的关系

| 上游假设 | 本项目做法 |
|---|---|
| 取点：`adb getevent`（Android）或透明窗（Windows 触屏） | **Linux evdev 多点触控协议 B（MT-B）** |
| 传输：同机 `serial.write()` | **TCP → 主机端 `bridge.py` → 虚拟串口** |
| 分区对齐：需要按分辨率另做一张整屏图 | **极坐标反向映射到原始分区图**，只要圆心 + 半径 |

## 引用

```
Protocol & zone tables:
  ERR0RPR0MPT/上游触屏实现 (MIT)
  ERR0RPR0MPT/majdata-windows-touch-panel (MIT)
Streaming:
  LizardByte/Sunshine, moonlight-qt
Adapter layer:
  majdata-touch-adapter (this repo, MIT)
```
