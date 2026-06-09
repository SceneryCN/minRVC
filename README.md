# Fuck RVC

> 免费、开源、UI 更好看的 RVC 桌面实时变声器。  
> 基于 Tauri 2 + Rust 音频引擎 + Python RVC sidecar。

这个项目的出发点很直接：市面上很多 RVC 变声软件本质上也是把 RVC 套一层壳，然后开始收费。那我也套一层壳，但不收费，尽量把 UI、交互、模型导入、素材处理、训练入口和常见软件问题一起做好。

项目目标不是重新发明 RVC，而是把开源 RVC 生态整理成一个更顺手的桌面工具：

```text
Mic -> Fuck RVC (Rust audio + DSP + Python RVC) -> 声卡 / 虚拟通道 -> OBS / StudioOne / Discord
```

## 当前功能

- 实时 RVC 变声：音色卡、音高、输入/输出设备、实时电平。
- 自定义音色：导入 `.pth`，可选 `.index`，应用自动复制并维护 manifest。
- 常规设置：响应阈值、声线粗细、检索特征占比、输入源响度融合、清辅音保护、响度、音高算法、采样率、chunk、buffer、crossfade、设备推荐档位等。
- 音高模型管理：RMVPE 模型状态、下载入口、加载本地 `rmvpe.pt`。
- 缓存式流式推理：缓存 ContentVec / F0 / Faiss 特征窗口，Generator 使用 realtime 裁剪接口，减少重复计算。
- 实时性能观测：显示 Rust DSP / WebSocket / 输出写入、ContentVec、F0、Generator、Faiss、SOLA、后处理等链路耗时，并自动标出当前最大瓶颈项。
- IPC 热路径：实时 PCM 优先走文件映射 shared-memory ring，控制 / profile 仍走 WebSocket；协商失败时自动回退 WebSocket binary。
- 降噪 / VAD：实时降噪、静音跳过，减少无意义 GPU 推理。
- 素材处理：Demucs、RoFormer、MDX23C 人声分离，支持进度、取消、打开输出目录。
- 模型训练页：训练包下载入口、加载本地 RVC-WebUI 训练包目录、GPU 检测、训练参数、预训练 G/D 权重入口和任务状态。
- 帮助页：模型下载清单、训练包地址、虚拟声卡/声卡路由说明。
- i18n：中文 / English。
- 主题：light / dark / system。
- UI 可读性：统一放大全局字号、去掉中文界面中过度字距，紧凑控件同步加高。
- 开源协议：MIT。

## 不内置大模型

RVC 相关模型、HuBERT、RMVPE、训练包、人声分离模型都很大，而且第三方音色模型版权情况复杂。所以本项目默认不把这些东西塞进安装包。

用户可以在帮助页打开下载地址，下载后按类型加载：

- `hubert_base.pt`：RVC 推理基础模型，体积较大；当前开发环境可通过 `sidecar/scripts/setup_rvc.py` 准备，应用内 HuBERT 单独导入入口还没做。
- `rmvpe.pt`：RMVPE 音高模型，可在「实时变声 -> 常规设置 -> 音高设置」加载。
- `.pth`：RVC 音色模型主体。
- `.index`：RVC 检索增强索引，可选。
- RVC-WebUI 训练包：解压后在“模型训练”页加载目录。

## 技术栈

| 层 | 技术 | 说明 |
|---|---|---|
| UI | React + TypeScript + Vite | 桌面应用界面、i18n、CSS Modules、全局字号 token |
| Shell | Tauri 2 | Windows / macOS 桌面外壳 |
| 音频 | Rust + cpal + ringbuf | 采集、输出、低延迟 SPSC 环形缓冲 |
| DSP | Rust | 降噪、VAD、音频状态 |
| IPC | WebSocket + mmap ring | 控制消息走 WebSocket；实时 PCM 优先走文件映射 shared-memory ring |
| 推理 | Python + FastAPI | RVC / F0 / ContentVec / Demucs / audio-separator |
| 模型 | PyTorch | RVC、RMVPE、FCPE、Crepe、Demucs、RoFormer、MDX23C |

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 开发环境

需要：

- Node >= 20
- pnpm >= 9
- Rust >= 1.77
- Python 3.10 或 3.11
- NVIDIA CUDA GPU 推荐；CPU 仅适合调试

```bash
pnpm install

cd sidecar
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

# 可选：专业人声分离模型后端（RoFormer / MDX23C）
# 这类模型较大，且 audio-separator 依赖更新快；建议在确认需要时单独安装。
pip install audio-separator

# 下载最小 RVC 推理源码 + hubert_base.pt + rmvpe.pt
python -m scripts.setup_rvc
cd ..

pnpm tauri:dev
```

没有运行 setup 也能打开应用，但真实 RVC 推理会缺基础模型，部分路径会回退到 pitch-shift，仅适合验证音频路由。

## 音频路由

不一定必须安装虚拟声卡。

如果你的声卡、StudioOne、OBS 或宿主软件能直接接收本应用输出，可以直接使用现有声卡/loopback/虚拟通道。只有当目标软件只能选择“麦克风输入”，又听不到本应用输出时，才需要 VB-Cable / BlackHole / VoiceMeeter 这类虚拟声卡。

参考：

- [docs/VB-CABLE.md](docs/VB-CABLE.md)
- [docs/STUDIOONE-OBS.md](docs/STUDIOONE-OBS.md)

## 模型和训练

音色模型导入规则：

- `.pth` 是 RVC 音色模型主体，必需。
- `.index` 是检索增强索引，可选；有它通常更像训练音色，但也可能带来音色过拟合或噪声。
- 导入后应用会复制文件到本地模型目录，并更新 manifest。

训练页当前提供：

- 训练包下载入口。
- 加载已解压的 RVC-WebUI 训练包目录。
- 本机 GPU 检测，显示 CUDA / MPS / CPU 状态。
- RVC v1/v2、epoch、batch size、采样率、F0 算法、保存间隔等训练参数。
- 训练用预训练 G / D 权重入口。
- 任务启动、轮询、取消、日志和产物路径展示。

G / D 权重不是最终音色模型。它们是训练用的预训练生成器 / 判别器权重，通常从 RVC-WebUI 相关 HuggingFace 资源下载，例如 `pretrained_v2/f0G40k.pth`、`pretrained_v2/f0D40k.pth`。如果不懂，可以先不选。

训练任务目前是“桌面入口 + sidecar 任务管理 + 外部 RVC-WebUI 训练包桥接”。不同训练包脚本参数不完全一致，所以仍需要用真实 RVC-WebUI 包做更多兼容测试。完整的“准备素材 -> 预处理 -> 特征提取 -> 训练 -> 生成 index -> 导入音色”还没有完全产品化串起来。

## 参考与依赖项目

这个项目站在一批开源项目上。核心参考和依赖如下：

| 项目 | 链接 | 用途 |
|---|---|---|
| RVC-Project / Retrieval-based-Voice-Conversion-WebUI | https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI | RVC 官方 WebUI、训练流程、推理模型结构。本项目 vendor 了最小推理源码子集。 |
| RVC-Project / Retrieval-based-Voice-Conversion | https://github.com/RVC-Project/Retrieval-based-Voice-Conversion | RVC 新版项目方向参考。 |
| HuBERT / ContentVec 权重 | https://huggingface.co/lj1995/VoiceConversionWebUI | RVC 特征提取基础模型下载来源。 |
| RMVPE 权重 | https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt | RMVPE 音高算法权重。 |
| PyTorch | https://pytorch.org/ | Python 侧模型推理和训练依赖。 |
| torchcrepe | https://github.com/maxrmorrison/torchcrepe | Crepe F0 算法实现。 |
| torchfcpe | https://github.com/CNChTu/FCPE | FCPE F0 算法实现。 |
| Demucs | https://github.com/facebookresearch/demucs | 内置人声分离模型。 |
| python-audio-separator | https://github.com/nomadkaraoke/python-audio-separator | RoFormer / MDX23C / UVR 系专业人声分离后端。 |
| Tauri | https://tauri.app/ | 桌面应用外壳。 |
| cpal | https://github.com/RustAudio/cpal | Rust 音频采集和输出。 |
| ringbuf | https://github.com/agerasev/ringbuf | 音频线程 SPSC 环形缓冲。 |
| FastAPI | https://fastapi.tiangolo.com/ | Python sidecar HTTP / WebSocket 服务。 |
| lucide-react | https://lucide.dev/ | UI 图标。 |

### 关于 RVC 官方代码

本项目没有声称重新发明 RVC。当前真实 RVC 推理链路参考并裁剪了 RVC-WebUI 的推理相关源码，例如 `infer_pack/models.py`、`rmvpe.py` 等；Rust 音频引擎、Tauri 命令、Python sidecar 协议、UI、模型导入、素材处理、训练入口是本项目自己的工程实现。

## 当前实现状态

| 模块 | 状态 |
|---|---|
| 实时变声 UI | 已实现，含设备推荐参数档位、实时链路 profiling 和更大的全局字号 |
| Rust 音频采集/输出/ring buffer | 已实现 |
| Tauri <-> Python WebSocket PCM 流 | 已实现 |
| Shared-memory PCM transport | 已实现文件映射 SPSC ring 协商和 WebSocket 回退；仍需真实音频链路长时间压测 |
| RVC 真实推理 | 已实现基础路径，仍需更多模型兼容测试 |
| RMVPE / FCPE / Crepe | 已接入；RMVPE / Crepe 在 CUDA 可用时会尝试 GPU，FCPE 使用当前配置设备，实际表现取决于 torchfcpe 版本 |
| 音色模型导入 | 已实现 |
| `.index` 导入 | 已实现 |
| 人声分离 Demucs | 已实现 |
| RoFormer / MDX23C | 已通过可选 audio-separator 后端接入，首次使用按需下载模型 |
| 模型训练页 | 已有入口、GPU 检测、训练包加载、参数表单、G/D 权重入口；已桥接外部训练脚本，仍需用真实 RVC-WebUI 包适配验证 |
| 缓存式流式推理 | 已实现 ContentVec / F0 / Faiss 滚动缓存；Generator 使用 RVC 官方 realtime infer 的 skip_head / return_length 裁剪旧上下文输出；热路径已复用部分 tensor / padding mask |
| 打包发布 | 基础脚本已有，仍需图标、签名、安装包验证 |

## 发布前状态

不是下面所有内容都“没做”。目前状态分三类：

### 功能缺口

这些属于明确还需要继续补产品入口或自动化的部分：

- HuBERT / ContentVec 基础模型还缺应用内导入和状态检测入口。
- 预训练 G / D 权重只提供本地选择入口，还没有下载清单和自动匹配采样率 / v1 v2 的逻辑。
- 训练产物生成后还缺“一键导入音色”的收尾动作；现在会展示产物路径，用户仍需要手动导入。
- 首次启动资源检查还可以更完整：HuBERT / RMVPE / 音色模型 / Python 环境缺失时，应给更集中、更明确的引导。

### 已实现但待真实环境压测

这些已经有代码，不是没做；只是需要用真实设备、真实模型、真实训练包验证稳定性：

- RVC 训练包桥接已实现外部脚本调用、任务状态、日志、取消和产物路径检测；但不同 RVC-WebUI 包的脚本参数并不完全统一，需要用真实包跑通预处理、特征提取、训练、index 生成全流程。
- audio-separator / UVR 系 RoFormer、MDX23C 已接入可选后端；首次下载模型、不同版本依赖和不同 GPU/CPU 环境还需要更多实测。
- Generator 已使用官方 realtime 裁剪接口减少旧上下文输出解码；如果用户加载的 vendor fork 不支持该签名，会自动回退整段窗口解码。
- Shared-memory PCM transport 已通过编译检查，但还需要在真实 sidecar venv、真实输入输出设备和真实模型下压测延迟、丢包、回退稳定性。
- 缺少真实模型矩阵测试：不同 `.pth` 结构、采样率、f0 配置、`.index` 质量都需要覆盖。
- macOS MPS、NVIDIA CUDA、CPU 的参数策略还需要用更多真实设备校准。

### 打包发布事项

这些是发布工程，不影响开发模式跑起来，但影响正式安装包质量：

- 打包发布还缺签名、安装包验证、首次启动资源检查和错误提示打磨。

## 目录结构

```text
.
├── src/                         # React 前端
│   ├── app/
│   ├── components/
│   ├── hooks/
│   ├── i18n/
│   ├── styles/
│   └── types/
├── src-tauri/                   # Rust / Tauri 后端
│   └── src/
│       ├── audio/
│       ├── commands/
│       ├── ipc/
│       ├── sidecar/
│       └── state.rs
├── sidecar/                     # Python 推理服务
│   ├── rvc_engine/
│   │   ├── server.py
│   │   ├── pipeline.py
│   │   ├── inference.py
│   │   ├── f0_extract.py
│   │   ├── feature_extract.py
│   │   ├── separate.py
│   │   ├── train.py
│   │   └── vendor/
│   └── scripts/setup_rvc.py
└── docs/
```

## 打包发布

参考 [docs/PACKAGING-WINDOWS.md](docs/PACKAGING-WINDOWS.md)。

```powershell
pnpm bundle:windows
```

macOS：

```bash
pnpm bundle:macos
```

发布前建议补齐：

- 应用图标。
- Windows/macOS 签名。
- HuBERT / RMVPE / 音色模型缺失提示。
- 首次启动下载 / 加载引导。
- 多设备实测。
- Shared-memory transport 长时间实时变声压测。

## License

[MIT](LICENSE)
