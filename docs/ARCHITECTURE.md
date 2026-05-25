# 架构

## 1. 数据流总览

```
┌──────────────────────────────────────────────────┐
│  React 前端                                       │
│   ├─ 5 个音色卡 / 设备选择 / 音高滑块             │
│   ├─ Zustand 全局 store                           │
│   └─ Tauri invoke / event                         │
└──────────┬───────────────────────────────────────┘
           │ Tauri command / event
           ▼
┌──────────────────────────────────────────────────┐
│  Rust 后端 (src-tauri)                            │
│   ├─ commands/      暴露给前端                    │
│   ├─ audio/                                       │
│   │   ├─ devices    枚举 + VB-Cable 识别          │
│   │   ├─ capture    cpal Input Stream（mic 线程） │
│   │   ├─ output     cpal Output Stream（spk 线程）│
│   │   ├─ ring       SPSC 环形缓冲                 │
│   │   └─ engine     编排 + tokio 任务             │
│   ├─ ipc/ws_client  连接 sidecar                  │
│   └─ sidecar/       Python 子进程生命周期         │
└──────────┬───────────────────────────────────────┘
           │ ws://127.0.0.1:8765/stream
           │  - text JSON 控制帧
           │  - binary f32 PCM 数据帧
           ▼
┌──────────────────────────────────────────────────┐
│  Python sidecar (FastAPI + uvicorn)               │
│   ├─ server.py      WebSocket / Health            │
│   ├─ pipeline.py    入口流水线                    │
│   ├─ feature_extract  HuBERT/ContentVec           │
│   ├─ f0_extract     RMVPE / FCPE / Crepe          │
│   ├─ inference      RVC + HiFiGAN                 │
│   ├─ sola           交叉淡化拼接                  │
│   └─ vad            能量门限                      │
└──────────────────────────────────────────────────┘
```

## 2. 线程模型

| 线程 | 来源 | 职责 |
|---|---|---|
| Main | Tauri runtime | UI / IPC / 命令分发 |
| Audio Capture | cpal callback | 把麦克风样本 push 进 SPSC ring |
| Audio Output | cpal callback | 从 SPSC ring pop 样本写入 VB-Cable |
| Tokio Send | tokio task | 从 mic ring 拉 chunk → WS send |
| Tokio Recv | tokio task | 从 WS recv → push 到 out ring |
| Python | sidecar 进程 | 阻塞推理（与本进程隔离，绕过 GIL） |

## 3. 关键决策

### 为什么选 Python sidecar 而不是纯 Rust？

参考 README 决策表。核心是：RVC 生态完全在 PyTorch + Python 上，纯 Rust 路径
（ONNX Runtime / Candle）需要重写整个特征提取链，且 obs-rvc 等项目证实
ContentVec/RMVPE 算子在 TensorRT 上有强制 CPU 回退，反而比 PyTorch 慢。

### 为什么 Rust 端仍然存在？

- cpal 在 Windows 上能拿到 WASAPI 独占模式，延迟比 PyAudio/SoundDevice 低
- 进程级隔离：Python 推理崩溃不影响音频线程，前端可立刻重连
- 安装包 + 启动时间：Tauri ~5MB shell，比 Electron 小一个数量级
- 后续若 ONNX 路径成熟，可直接把 sidecar 替换为 Rust ONNX，IPC 协议不变

### 为什么要 SPSC 环形缓冲，不直接 channel？

cpal 的 callback 在专用音频线程上，禁止做任何分配/系统调用/锁等待。
SPSC ring（无锁、固定大小）是音频领域的标准做法，毫秒级即可送达 Tokio 任务。

### 为什么 chunk_size = 1024 @ 48kHz？

≈ 21ms 采样窗口。RVC 实时变声的「合理延迟」范围是 80–250ms（块大小 +
HuBERT 上下文 + 输出缓冲），其中模型推理是大头，缓冲只占其中一小部分。
1024 是延迟与 IPC 调用次数的甜点。

## 4. 错误处理

- Rust 侧统一 `AppError`（thiserror），通过 Tauri 命令返回字符串给前端
- Python 侧异常通过 `{"type":"error","message":...}` 文本帧反向通知
- WebSocket 断开会让两个 tokio 任务自然 break，前端通过 `engineStatus` 轮询发现

## 5. 状态切换

```
       start_engine
Stopped ──────────► Starting ──────────► Running
   ▲                                        │
   │             stop_engine                │
   └──── Stopped ◄────── Stopping ◄─────────┘
```

错误（任意时刻）→ `Error`，前端展示 errorMessage，需要用户手动 stop 后重启。
