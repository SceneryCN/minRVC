# 音频处理 / 音频分离

声变内置两条「跟人声打交道」的管线，目标完全不同，**别混淆**：

| 模块 | 场景 | 实时性 | 库 / 模型 | License |
|---|---|---|---|---|
| **实时降噪 + VAD** | 直播变声前的预处理 | 在线，<20ms | nnnoiseless (RNNoise) + Silero VAD | MIT / BSD |
| **离线人声分离** | 自训练 RVC 模型时分离训练素材 | 离线批处理 | Demucs v4 | MIT |

---

## 1. 实时降噪 + VAD（直播链路）

### 为什么要做？

麦克风录到的不只是你的人声，还有：

- 机械键盘咔哒声
- 风扇 / 散热器嗡嗡声
- 电源 / USB 电流声 hiss
- 突然的咳嗽 / 鼠标点击

这些噪声会被 RVC 一并「翻译」过去，变出来的声音就一团模糊。

### 管线

```
Mic → cpal capture → [RNNoise 降噪] → [Silero VAD] → ringbuf → sidecar (RVC) → ringbuf → cpal output → VB-Cable
                          ↑                ↑
                    48 kHz / 10 ms     16 kHz / 32 ms
                    可调强度 0~100%    可调阈值 0.1~0.9
```

- **降噪**：[`nnnoiseless`](https://crates.io/crates/nnnoiseless)（RNNoise 纯 Rust 移植），帧 480 sample，零外部依赖
- **VAD**：[`silero-vad-rust`](https://crates.io/crates/silero-vad-rust)，ONNX 模型已捆绑在 crate 里，**无需额外下载**

### 跑在哪里？

跑在 Rust 端 `src-tauri/src/audio/dsp/`，**在 mic_ring 之后、WebSocket 之前**。

好处：
- sidecar 收到的是干净人声，GPU 直接节省 ≥50%
- VAD 判定为静音的 chunk 根本不进 WebSocket，省带宽
- DSP 是 tokio 异步任务，与 cpal 回调线程解耦（cpal 回调禁止阻塞）

### UI 操控

「实时变声」tab 底部的「降噪 / VAD」面板：

- 降噪开关 + 强度滑条（0=原信号 / 1=完全降噪输出）
- VAD 开关 + 阈值（推荐 0.5）
- VAD 防抖：开始说话最小持续 ms / 停止说话最小静音 ms
- 实时状态灯：正在说话 / 静音 + VAD 概率条

### 限制

| 限制 | 说明 |
|---|---|
| RNNoise 仅 48 kHz | 帧大小固定 480。其它采样率下降噪自动旁路（信号不变），UI 会显示 `denoiseActive=false` |
| Silero 仅 16 kHz | 内部用 N:1 整数比下采到 16 kHz；非整数比（罕见）时 VAD 自动旁路 |
| Silero 模型 ~2 MB | crate 里已捆绑，无需额外下载 |

---

## 2. 离线人声分离（素材实验室）

### 为什么要做？

你想训练一个全新的「奶青音」模型？需要 ≥10 分钟的纯人声素材。
来源往往是 B 站视频 / 翻唱 / 直播切片，**带 BGM**。

UVR / Demucs 可以把混音抠成：
- `vocals.wav` — 纯人声（拿去训 RVC）
- `accompaniment.wav` — 伴奏（丢了）

### 实时人声分离可不可行？

**不可行**。

- MDX-Net / Demucs 等模型需要 1~2 秒频谱上下文做 STFT
- 物理最低延迟：GPU 1.75s，CPU 3s+
- 直播变声场景下完全用不了

我们这部分是**离线批处理**，不进实时管线。

### 管线

```
File (mp3/wav/...) → Tauri 拖入 → Tauri 命令转发 → Python sidecar /separate
                                                      ↓
                                                 Demucs htdemucs (默认)
                                                      ↓
                                          vocals.wav + accompaniment.wav
```

### 模型选择

UI 下拉框预置 3 个：

| 模型 | 体积 | 适合 | 备注 |
|---|---|---|---|
| `htdemucs` | ~80 MB | 人声 + 流行 / 摇滚 | **默认**，平衡速度与质量 |
| `htdemucs_ft` | ~80 MB | 极致质量 | 多次推理叠加，耗时 4× |
| `mdx_extra` | ~100 MB | 电子乐 / EDM / 嘻哈 | 对鼓点和合成器更友好 |

> Demucs 模型首次使用会自动从 [facebookresearch/demucs](https://github.com/facebookresearch/demucs) 拉取到 torch hub 缓存（`~/.cache/torch/hub/checkpoints/`），后续复用本地缓存。

### 输出

落到：
```
{data_dir}/separation/{session_id}/
  ├── vocals.wav
  └── accompaniment.wav
```

`{data_dir}` 各平台位置：
- macOS: `~/Library/Application Support/rvc-voice-changer/`
- Windows: `%LOCALAPPDATA%\rvc-voice-changer\`
- Linux: `~/.local/share/rvc-voice-changer/`

UI 完成后会展示路径，点 ↓ 按钮直接打开所在文件夹。

### 取消

任务运行中点「取消」即可。Demucs 内部正在跑 `apply_model` 时不可中断，但我们会在每个阶段（加载、读取、分离前）检查 cancel flag，最坏等 30 秒左右一定会停。

### 加速

- **Apple Silicon**：自动用 MPS（Metal Performance Shaders），M-Pro / M-Max 实测比 CPU 快 5×
- **NVIDIA**：自动用 CUDA
- **CPU only**：兜底，7 分钟歌大约 5 分钟（M1 Air）/ 2 分钟（i9）

### 命令行兜底

如果你不想开 GUI，也可以直接用 Python：

```bash
cd sidecar
python -c "
from rvc_engine.config import SidecarConfig
from rvc_engine.separate import SeparationManager
import time
mgr = SeparationManager(SidecarConfig())
job = mgr.start('/path/to/song.mp3', model='htdemucs', two_stems=True)
while job.state in ('pending', 'running'):
    print(f'{job.state} {job.progress*100:.0f}%')
    time.sleep(1)
print('done', job.vocals_path, job.other_path)
"
```

---

## 3. 为什么不集成 DeepFilterNet？

调研过程中我们对比了：

| 候选 | License | 延迟 | 质量 | Rust 集成成本 |
|---|---|---|---|---|
| **nnnoiseless (RNNoise)** | BSD | <10ms | 中等 | ⭐ 极低（5 行 API） |
| **DeepFilterNet 3** | MIT | 1.7ms / 帧 | 高 | ⭐⭐⭐⭐ 极高（需 STFT + ERB + 3 ONNX 协同） |
| **NVIDIA RNNoise GPU** | 闭源 | 中 | 中高 | 闭源不可用 |

DeepFilterNet 在 Rust 端集成需要从零写复数 STFT、ERB band 转换、三个 ONNX 模型协同的 ~1500 行胶水。
我们当前架构已经预留了 backend trait（`audio::dsp::denoise::*`），如果未来用户反馈 RNNoise 不够，可平滑替换。

Pull Request welcome.

---

## 4. 故障排查

| 现象 | 可能原因 | 修复 |
|---|---|---|
| UI 显示「降噪未生效」 | 麦克风采样率 ≠ 48 kHz | macOS 在「音频 MIDI 设置」里改成 48000 Hz；Windows 控制面板 → 录音设备 → 高级 |
| VAD 总是判定为「静音」 | 阈值太高 / 麦克风电平太低 | 阈值降到 0.3，并检查输入电平表 |
| VAD 总是判定为「说话」 | 阈值太低 / 房间噪音大 | 先开降噪，再把 VAD 阈值升到 0.6+ |
| 离线分离一直停在「loading model」 | Demucs 首次拉模型，~80 MB | 检查网络；若被墙，预先 `python -c "from demucs.pretrained import get_model; get_model('htdemucs')"` |
| 分离后 vocals.wav 有伴奏残留 | 模型选错了 | 切换 `htdemucs_ft`（更慢但更干净）或 `mdx_extra`（电子乐） |

---

## 5. 引用

- RNNoise: Valin, J.M. *A Hybrid DSP/Deep Learning Approach to Real-Time Full-Band Speech Enhancement*. MMSP 2018.
- Silero VAD: <https://github.com/snakers4/silero-vad>
- Demucs v4: Rouard, S. et al. *Hybrid Transformers for Music Source Separation*. ICASSP 2023.
