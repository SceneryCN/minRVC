# Tauri ↔ Python sidecar 通信协议

URL：`ws://127.0.0.1:8765/stream`（端口可由 sidecar `--port` 修改）

## 帧类型

WebSocket 同时使用 **text** 与 **binary**：
- text：控制帧（JSON）
- binary：音频帧（小端 f32 PCM mono）

## 客户端 → 服务端

### init（必须最先发）

```json
{ "type": "init", "voice_id": "yujie", "pitch": 0, "in_sr": 48000, "out_sr": 48000 }
```

服务端收到后加载模型，回 `{"type":"ready"}`。
此后客户端可以发送 binary 音频帧。

### 音频帧（binary）

`Vec<f32>` LE 字节序，长度必须是 4 的倍数。
建议每帧 256–4096 样本。

### set_voice / set_pitch（运行中切换）

```json
{ "type": "set_voice", "voice_id": "loli" }
{ "type": "set_pitch", "pitch": 4 }
```

## 服务端 → 客户端

```json
{ "type": "ready" }
{ "type": "status", "state": "voice_changed" | "pitch_changed" }
{ "type": "error",  "message": "..." }
```

binary：变声后的 f32 PCM mono @ `out_sr`，长度可能与输入不同。
