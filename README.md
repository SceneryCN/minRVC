# 声变 (RVC Voice Changer)

> 傻瓜式实时 RVC 变声器，基于 **Tauri 2 + Rust + Python sidecar**。

5 种预置音色、一键启动，配合 VB-Cable 虚拟声卡接入直播链路：

```
Mic → 声变 (Rust 音频引擎 + Python RVC 推理) → VB-Cable → StudioOne / OBS
```

---

## 功能

- ✅ 5 个预置音色按钮：御姐 / 萝莉 / 小男孩 / 奶青 / 青叔
- ✅ 自动检测虚拟声卡（VB-Cable / BlackHole / VoiceMeeter）
- ✅ 实时 VU 表（输入 / 输出）
- ✅ 音高调节（±24 半音）
- ✅ 模型本地导入 / 切换
- ✅ Windows + macOS 跨平台（VB-Cable 替换为 BlackHole）
- ✅ **实时降噪（RNNoise）+ VAD（Silero）**：纯 Rust，10ms 帧，把噪声挡在 RVC 之前
- ✅ **离线人声分离（Demucs v4）**：从 BGM 里抠人声，给自训练 RVC 准备素材

## 技术栈

| 层 | 选型 | 备注 |
|---|---|---|
| UI | React 18 + TypeScript + Vite | 严格 TS、i18n、CSS Modules |
| Shell | Tauri 2 | Windows / macOS 桌面 |
| 音频 | Rust + cpal + ringbuf | WASAPI / CoreAudio，低延迟 SPSC |
| 推理 | Python sidecar (FastAPI + WebSocket) | RVC + RMVPE + HiFiGAN |
| 通信 | 本地 WebSocket（二进制 PCM f32） | 单进程、无 Python GIL 阻塞前端 |

详见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 开发环境

需要：

- Node ≥ 20、pnpm ≥ 9
- Rust ≥ 1.77
- Python 3.10–3.11
- NVIDIA GPU + CUDA 12.1（推荐，CPU 模式仅供调试）

```bash
# 1. 前端依赖
pnpm install

# 2. Python sidecar 依赖（GPU）
cd sidecar
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

# 3. 一键下载 RVC 推理源码 + 基础模型（hubert_base.pt + rmvpe.pt）
python -m scripts.setup_rvc
cd ..

# 4. 启动开发模式（前端 + Tauri + sidecar 自动管理）
pnpm tauri:dev
```

> macOS 开发期可暂时不安装 PyTorch GPU 版（用 CPU），仅用于联调音频管线。
> 真正出活儿需要 Windows + NVIDIA。
>
> 没运行 setup 也能启动应用，只是会走 **pitch-shift 回退路径**（不真变声，仅变调），方便先验证音频路由。

---

## 直播链路配置

1. 安装 [VB-Cable](https://vb-audio.com/Cable/)（详见 [`docs/VB-CABLE.md`](docs/VB-CABLE.md)）
2. 在「声变」里：
   - **麦克风** = 你的物理麦克风
   - **虚拟声卡输出** = `CABLE Input (VB-Audio Virtual Cable)`
3. 在 OBS / StudioOne 里：
   - **麦克风源** = `CABLE Output (VB-Audio Virtual Cable)`
4. 详见 [`docs/STUDIOONE-OBS.md`](docs/STUDIOONE-OBS.md)

---

## 音色模型

5 种预置音色对应的开源模型获取方式见 [`docs/MODELS.md`](docs/MODELS.md)。

简而言之：
- 御姐 / 萝莉 / 青叔 / 小男孩 → 妙音 RVC 工坊（部分免费、部分付费）+ HuggingFace 大量开源
- 奶青 → 没有完全匹配的预训练，建议自训练或用「奶樱」+ 微调

> ⚠️ 所有第三方模型版权状况复杂，**仅限学习研究**，商用务必自训练或获得授权。

---

## 打包发布

详见 [`docs/PACKAGING-WINDOWS.md`](docs/PACKAGING-WINDOWS.md)。两条路：

**A. 本机 Windows 一键打包**

```powershell
pnpm bundle:windows
# → src-tauri/target/release/bundle/msi/声变_*.msi
# → src-tauri/target/release/bundle/nsis/声变_*-setup.exe
```

**B. GitHub Actions 远程出包**（不用买 Windows）

```bash
git tag v0.1.0 && git push origin v0.1.0
# → Actions 自动跑 windows-latest + macos-14 → 草稿 Release
```

CI workflow 已写好在 [`.github/workflows/release.yml`](.github/workflows/release.yml)。

> **关键约束**：PyInstaller 不能跨平台，**打 Windows 包必须有 Windows 环境**（CI runner 即可）。
> macOS 用 `pnpm bundle:macos` 一键出 `.dmg`。

---

## 目录结构

```
.
├── src/                         # React 前端
│   ├── app/                     # 顶层组件
│   ├── components/<name>/index.tsx  # 可复用组件（kebab-case + index 入口）
│   ├── hooks/                   # 自定义 hooks
│   ├── utils/                   # 纯工具函数
│   ├── i18n/                    # zh-CN / en
│   ├── styles/                  # 全局变量与 reset
│   ├── constants/               # 5 个音色等业务常量
│   └── types/                   # 与 Rust 端对齐的类型
├── src-tauri/                   # Rust 后端
│   └── src/
│       ├── audio/               # cpal 采集 / 输出 / SPSC 环形缓冲
│       ├── ipc/                 # WebSocket 客户端 → Python sidecar
│       ├── sidecar/             # Python 进程生命周期
│       ├── commands/            # Tauri invoke 入口
│       ├── error.rs / state.rs / lib.rs / main.rs
├── sidecar/                     # Python 推理服务
│   ├── rvc_engine/
│   │   ├── server.py            # FastAPI + WS
│   │   ├── pipeline.py          # 推理总流水线
│   │   ├── feature_extract.py   # HuBERT
│   │   ├── f0_extract.py        # RMVPE
│   │   ├── inference.py         # RVC (TODO 接入官方代码)
│   │   ├── sola.py              # 块拼接
│   │   ├── vad.py               # 静音检测
│   │   └── config.py
│   └── build_sidecar.py         # PyInstaller 打包
└── docs/
    ├── ARCHITECTURE.md
    ├── PROTOCOL.md              # Tauri ↔ sidecar IPC 协议
    ├── MODELS.md                # 5 种音色获取指南
    ├── VB-CABLE.md
    └── STUDIOONE-OBS.md
```

---

## 当前实现状态

| 模块 | 状态 |
|---|---|
| Rust 音频管线（cpal 采集/输出/环形缓冲/虚拟声卡识别） | ✅ |
| Tauri ↔ Python WebSocket 二进制流 | ✅ |
| Python sidecar 框架（FastAPI / WS / SOLA / VAD / Pipeline） | ✅ |
| **真实 RVC 推理（ContentVec + RMVPE + SynthesizerTrn v1/v2 + Faiss）** | ✅ vendor 上游源码 + 流式上下文 |
| **实时降噪（nnnoiseless）+ VAD（Silero ONNX）** | ✅ Rust 原生，10ms 帧，可调强度/阈值 |
| **离线人声分离（Demucs v4：htdemucs / htdemucs_ft / mdx_extra）** | ✅ 素材实验室 tab，进度/取消/打开文件夹 |
| 5 个预置音色按钮 + 模型导入 | ✅（无模型时回退到 pitch-shift） |
| 三主题（light/dark/system）+ lucide 图标系统 | ✅ |
| Tab 切换（实时变声 / 素材实验室） | ✅ |
| PyInstaller sidecar 打包脚本（含 vendor 收集） | ✅ |
| 一键 setup 脚本（vendor 源码 + 基础模型下载） | ✅ |
| 图标 / 应用签名 | ❌ 需补 |

> 启动时按 voice 自动判断使用真实 RVC 还是 pitch-shift fallback，**两条路径都能即时切换**，方便先把整条音频管线（设备 → 缓冲 → IPC → 输出）跑通再上模型。

---

## License

MIT
