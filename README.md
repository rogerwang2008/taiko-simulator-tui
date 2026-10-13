# 太鼓模拟器 (taiko-simulator-tui)

把键盘从左到右切成四条竖带，敲下任意键即刻发声的低延迟太鼓模拟器。鼓面 (don) 与鼓边 (ka) 分送左右声道，
界面用 [Textual](https://textual.textualize.io/) 绘制，分区边界可视化调整并即时保存到本地。

![python](https://img.shields.io/badge/python-3.14%2B-3776AB?logo=python&logoColor=white)
![platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS-4B5563)
![audio](https://img.shields.io/badge/audio-WASAPI%20%7C%20CoreAudio-0EA5E9)

![界面截图](docs/screenshot.svg)

## 特性

- **四区即时发声** —— 键盘按物理横向位置切片，四个区是键盘上真实的四条竖带，不用记零散键位
- **低延迟** —— 按键到出声实测 25–30 ms，击鼓热路径中位数 0.04 ms，无内存分配
- **声道分离** —— 左区只出左耳、右区只出右耳，串音实测为 0
- **可视化配置** —— `←` / `→` 直接拖动分界线，改动立即落盘
- **长按只响一声** —— 按住键不会连发
- **跨平台** —— Windows 与 macOS 共用同一套代码

## 安装

需要 **Python 3.14+**，推荐用 [uv](https://docs.astral.sh/uv/)：

```bash
git clone https://github.com/rogerwang2008/taiko-simulator-tui.git
cd taiko-simulator-tui
uv sync
uv run taiko-simulator-tui
```

也可以直接装成命令行工具（音频素材已打进 wheel）：

```bash
uv tool install git+https://github.com/rogerwang2008/taiko-simulator-tui
taiko-simulator-tui
```

## 四个区

| 区 | 声音 | 声道 | 颜色 | 默认按键 |
| --- | --- | --- | --- | --- |
| 左鼓边 | rim (ka) | ← 左 | 蓝 `#3b9dff`（冷） | `1 2 3 4 Q W E A S D Z X` |
| 左鼓面 | center (don) | ← 左 | 红 `#ff5a4d`（暖） | `5 6 7 R T Y F G H C V B` |
| 右鼓面 | center (don) | 右 → | 琥珀 `#ffc233`（暖） | `8 9 0 U I O J K L N M , .` |
| 右鼓边 | rim (ka) | 右 → | 青 `#22c3c9`（冷） | `- = P [ ] \ ; ' /` |

鼓面用暖色、鼓边用冷色，四个区色相各不相同（相邻区相差 206° / 38° / 140°），两条分界线在键盘和
面板上都一眼可辨。

分区按每个键的**物理横向位置**（含各行交错偏移）划分，所以它是真正的纵向切片，而不是四组零散的键。

## 按键

| 键 | 作用 |
| --- | --- |
| 布局内任意键 | 敲击对应区，立即发声并闪烁反馈 |
| `↑` / `↓` | 选择要调整的边界 `^1` / `^2` / `^3` |
| `←` / `→` | 以 0.25 键位为步长移动选中的边界 |
| `Ctrl+R` | 恢复默认分区 |
| `Esc` / `Ctrl+Q` | 退出 |

边界每次移动都会立刻保存，无需确认。

## 长按

按住一个键只会发出一声。系统在按住期间会不断重发按键事件，而终端从不报告按键释放（只在 kitty 键盘
协议的 event-type 标志下才报告，Textual 未申请该标志，多数终端也未实现），所以这里靠事件**间隔**
识别长按：同一个键两次事件间隔小于 60 ms，不可能是人按的，判为系统重复。

- 长按 2 秒（Windows 默认 500 ms 延迟 / 33 ms 间隔）：从约 30 次发声降到 **2 次**
- 单手连打 12 次/秒、双手交替 20 次/秒、同键双击 100 ms：**全部保留，不丢音**

60 ms 是刻意选的门限：它低于任何平台的最快重复间隔（Windows 最快约 33 ms，macOS 约 15–30 ms），
又高于人类在同一键上连打的速度上限，因此它只会漏判系统重复，不会吃掉真实敲击。

## 配置

分区边界存在 `platformdirs` 的用户配置目录下：

| 平台 | 路径 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\taiko-simulator-tui\config.json` |
| macOS | `~/Library/Application Support/taiko-simulator-tui/config.json` |

内容只有分区边界（键位单位，键盘横向范围 0–12.5）：

```json
{ "version": 1, "boundaries": [3.25, 6.25, 9.5] }
```

文件损坏或数值非法时自动回退默认分区。

## 低延迟

按键到出声的实测预算（Headphone Realtek / WASAPI 共享模式 / 48 kHz）：

| 环节 | 实测 |
| --- | --- |
| 击鼓热路径（`on_key` → 写入环形缓冲） | 中位数 **0.04 ms**（无内存分配、单写单读） |
| 设备输出缓冲 | **22.0 ms**（WASAPI 共享模式在本机的下限） |
| 回调成簇触发，拾取新写入的数据 | 平均再等 **~5 ms** |
| 合计 | **约 25–30 ms** |

实现上是一个常驻输出流加环形缓冲：触发时把预先分好声道的样本**加性写入读指针处**，所以并发敲击
自然混音，快速连打时由回调里的 `np.clip` 限幅。

样本加载时做了三件事，都是为了让「敲击瞬间」真的对齐按键瞬间：

1. **裁掉前导静音** —— 原始 mp3 每次敲击前有约 70 ms 静音，不裁就等于凭空加 70 ms 延迟
2. **裁掉尾部静音** —— 11.08 s 的素材里有效声音只有 1.5–1.8 s
3. **峰值归一到 0.6** —— 原始 rim 峰值只有 center 的四分之一，不归一鼓边几乎听不见；
   留出余量是因为左右手经常同时击打

> 独占模式下实测可到 4.3 ms，但它会独占音频设备导致其他应用静音，因此本项目刻意不用 —— 便于边听
> 音乐边练。

## 跨平台

Windows 与 macOS 运行同一套代码，差异只有两处，且都以 `sys.platform` 隔离：

| 差异 | Windows | macOS / Linux |
| --- | --- | --- |
| 输出设备 | 显式选 WASAPI（PortAudio 默认的 MME 会多约 100 ms 缓冲） | 当前 host API 的默认输出设备 |
| 控制台编码 | 切到 UTF-8（旧代码页如 cp936 无法编码 Textual 字形，会让输出线程抛异常并静默停更），退出时还原 | 空操作 |

配置目录、音频素材、键盘布局解析都不含平台假设。

## 项目结构

```
src/taiko_simulator_tui/
  audio.py      解码 / 裁剪 / 归一 / 重采样，环形缓冲与输出流
  keyboard.py   键盘布局、交错偏移、四分区解析、边界钳制、长按判定
  config.py     配置读写与校验
  app.py        Textual 界面
  assets/audio/ center1.mp3 鼓面、rim1.mp3 鼓边
```

## 已知限制

- **长按会响两声**：首次系统重复（约 500 ms 后）与「用户真的又按了一次」在时间上完全同形，
  终端不报告按键释放，无法区分。多的一声只出现在按住时，正常敲击不受影响。
- **调慢系统重复率会削弱长按抑制**：若把重复间隔设为 ≥ 60 ms，间隔已落在人类可及范围，
  无法与真实敲击区分。
- **分区只覆盖主键区四行**（数字行、Q 行、A 行、Z 行），不含空格与功能键。
