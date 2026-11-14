# 架构与实现细节

> 阅读时间约 8 分钟。这里只写"为什么这样设计"，使用说明在 [README](../README.md)。

## 1. 线程模型

```
┌─────────────┐   frame   ┌──────────────┐  event  ┌──────────────┐
│ camera      │──────────▶│ detect       │────────▶│ render(仅警报)│
│ 15 fps 抓帧 │ 最新帧槽  │ 10 Hz 检测   │ 触发/收尾│  ~30 fps 绘制 │
└─────────────┘           └──────────────┘         └──────┬───────┘
                                                          │ 预乘 BGRA
                                                   ┌──────▼───────┐
                                                   │ overlay      │
                                                   │ Win32 消息循环│
                                                   └──────────────┘
```

- **camera**：`cv2.VideoCapture` 抓帧，写入"最新帧槽"（`_frame/_stamp/_seq`）。
  检测线程永远取最新一帧，慢的检测不会造成积压——这是网络摄像头看门狗最常见的坑。
  抓帧按 `max_fps=15` 自己限速（检测只需要 10 Hz，没必要吃 30 fps 的 CPU）。
- **detect**：按 `detect_interval_ms`（默认 100 ms）循环。只有 `seq` 变化才做检测，
  重复帧直接跳过。检测结果进 `IntruderLogic`，返回 `trigger` / `release`。
- **render**：**只在警报期间存在**。结束即退出线程、窗口隐藏，所以空闲时没有渲染开销。
- **overlay**：唯一接触 Win32 的线程。它只做三件事：泵消息、memmove 一帧、喂给
  `UpdateLayeredWindow`。**不做任何绘制**，绘制全在渲染线程的 numpy/PIL 里完成。

线程数在警报期间为 4（含热键消息线程），空闲时 3。

## 2. 检测与判定

- 级联：`haarcascade_frontalface_default.xml` + `haarcascade_profileface.xml`（及其水平翻转，
  这样左右侧脸都能命中）。
- 先在 320 px 灰度图上检测（`equalizeHist` 提对比），再把框映射回原始分辨率。
- NMS 用 IoU 0.35 去重，正面框（score 1.0）优先于侧脸框（0.7）。
- **"你"是谁**：面积最大的那张脸记为 owner，其余与 owner 的 IoU < 0.35 的算"他人"。
  这样做的代价是"你"必须离镜头最近/最大——对一个防偷窥工具来说这恰好是合理假设。
- 去抖：人数 > `allowed_own_faces` 且连续 `confirm_frames` 帧才触发；触发后进入
  `cooldown_s` 冷却；房间安静 `release_s` 秒才收尾。

实测 4.0 ms/帧 @ 640×480 → 320 px，含正面 + 双侧脸。

## 3. 覆盖层（Win32）

手工 ctypes 封装，没有 pywin32 依赖：

| 细节 | 原因 |
|---|---|
| 单窗口覆盖**虚拟屏** | 多显示器 / 混合 DPI 一次搞定；比例无需换算 |
| `WS_EX_LAYERED \| TRANSPARENT \| TOPMOST \| TOOLWINDOW \| NOACTIVATE` | 分层 + 点击穿透 + 置顶 + 不进任务栏 + 不抢焦点 |
| `WM_NCHITTEST` 返回 `HTTRANSPARENT` | 双保险：即使某处没被 `WS_EX_TRANSPARENT` 覆盖也照样穿透 |
| `UpdateLayeredWindow` + **预乘 BGRA** | 唯一支持逐像素 alpha 的上屏方式；预乘必须在生产者侧做好 |
| DIB 用**负高度**（top-down） | 与 numpy 的行序一致，省一次翻转 |
| `SetProcessDpiAwarenessContext(-4)` | Per-monitor v2，缩放屏上也对齐物理像素 |

两个必须显式写 `argtypes/restype` 的地方：

```python
user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = c_longlong
```

`lParam` 是**有符号 64 位**，高位为 1 时（鼠标坐标、屏幕尺寸消息常见）如果不声明
`LPARAM`，ctypes 会按 `c_int` 转换并抛 `OverflowError: int too long to convert`，
窗口过程每收到一条消息就报一次异常，结果是覆盖层根本不显示。

**帧保鲜**：`push()` 记录"最后一次推帧时间"，覆盖层线程在 200 ms 内没有新帧就保持
上一帧不动，超过才隐藏。早期版本"消费即清空 + 立刻隐藏"，导致窗口在 show/hide 之间
抖，肉眼永远看不到——这是端到端截图验证才暴露出来的问题。

## 4. 渲染与性能

- 画布尺寸 = 虚拟屏 × `quality`（默认 0.5），特效在这个小画布上绘制，再把**预乘后**的
  图像线性放大到屏幕。预乘图做线性插值仍然自洽（RGB 与 A 一起被平滑）。
- 放大策略自适应：帧耗时紧 → `NEAREST`（约 2 ms，1707×1067）；宽裕 → `BILINEAR`（约 17 ms）。
- 分辨率也自适应：`ema` 帧耗时 > 38 ms 就按 0.88 递减（下限 0.26），< 22 ms 再升回 `quality`。
- 逐帧固定 30 fps 预算，超预算不 sleep，欠预算补 sleep——不会为了追帧把 CPU 打满。
- 热点函数优化记录：`hsv_gradient` 原来是"6 倍大的查找表"（0.45 MP 下要分配 ~80 MB），
  改成三条相位余弦波，从 **66 ms 降到 30 ms**；`premultiply_bgra` 从整幅 uint16 提升
  改为单通道 uint16 计算，省掉一半内存带宽。

## 5. 音效

`numpy` 合成 44.1 kHz / 16 bit PCM → 在内存里拼 WAV 头 → `winsound.PlaySound(SND_MEMORY | SND_ASYNC)`。
没有任何音频文件，音色由参数（正弦/方波/噪声 + 包络）定义，`volume` 直接对采样幅度缩放。
`SoundPlayer` 在 daemon 线程按 `repeat`/`delay_ms` 播放，可 `SND_PURGE` 立即停止。

## 6. 配置与自启动

- 路径 `%APPDATA%\PrivacyGuard\config.json`，`load` 时 `deep_merge(DEFAULTS, 用户配置)`
  再 `clamp_values`，因此手改出错的字段不会让界面卡死或窗口变成 0 尺寸。
- 写入用 `tmp + os.replace` 原子替换，断电不会留半个文件。
- 开机自启写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`，命令是
  `"<pythonw.exe>" -m privacyguard --no-panel`（用 pythonw 不留黑框）。

## 7. 验证方式

不只是"看起来能跑"：

| 脚本 | 证明什么 |
|---|---|
| `tests/test_core.py` | 11 个单元测试：配置夹取、触发/收尾状态机、16 个特效都能出 RGBA、序列器轮播、预乘数值、音效 WAV、热键解析 |
| `tests/prove_overlay.py` | 白色窗口 + 纯红色覆盖层 → 截图里窗口变红：**覆盖层真的合成上屏了** |
| `tests/prove_effect.py` | 真实特效引擎 → 覆盖层 → 屏幕像素，逐个特效截图核对 |
| `tests/bench_loop.py` | 真实渲染线程的 fps / 自适应质量 |
| `tests/shot_panel.py` | 四个面板页面逐个截图，GUI 布局回归 |

环境相关的坑（写在这里省得再踩）：

- OpenCV 5.x 的 wheel **不带** Haar XML，必须 4.12.0.88。
- 某些精简 Python 缺 Tcl/Tk 数据文件：`import tkinter` 能过，`Tk()` 报
  `Can't find a usable init.tcl` —— 这种解释器只能 `--no-panel`。
- 本机 git 若配过失效的 `http.proxy`，推送会一直连不上，需要 `-c http.proxy= -c https.proxy=` 绕过。
