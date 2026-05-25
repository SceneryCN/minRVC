# RVC Sidecar

Python 推理服务，由 Tauri 主进程拉起。负责：

- ContentVec / HuBERT 特征提取
- RMVPE F0 提取
- RVC 模型推理（v1/v2 自适应）+ Faiss 检索增强
- HiFiGAN 声码器（在 SynthesizerTrn 内部）
- SOLA 块拼接 + VAD

## 1. 第一次启动（一次性）

### 1.1 准备 Python 3.10 / 3.11 环境

> ⚠️ 必须 3.10 或 3.11。fairseq 在 3.12+ 上无法编译。

```bash
# Windows
py -3.11 -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3.11 -m venv .venv
source .venv/bin/activate
```

### 1.2 安装依赖

```bash
# GPU (NVIDIA, CUDA 12.1)
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu121

# CPU-only（仅调试，实时性能不足）
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

### 1.3 一键 setup（vendor 源码 + 下载基础模型）

```bash
python -m scripts.setup_rvc
```

会做 4 件事：
1. 从 RVC-Project 仓库 fetch 必要的 6 个推理源文件到 `sidecar/vendor/rvc/`
2. 自动改写 import 路径到本地命名空间
3. 下载 `hubert_base.pt`（~360MB，ContentVec）到数据目录
4. 下载 `rmvpe.pt`（~180MB，F0 提取）到数据目录

可选参数：
- `--skip-weights`：只 vendor 源码，跳过权重下载（CI / 离线分发）
- `--force`：强制重新下载已有文件
- `--clean`：删除 vendor/rvc 后重新开始

### 1.4 把音色 .pth 模型放到对应目录

```
~/AppData/Local/rvc-voice-changer/models/voices/   # Windows
~/Library/Application Support/rvc-voice-changer/models/voices/   # macOS
└── yujie/
    ├── yujie.pth
    └── yujie.index    # 可选，用于 Faiss 检索增强
```

详细模型来源见 [`docs/MODELS.md`](../docs/MODELS.md)。

## 2. 启动 sidecar

```bash
python -m rvc_engine.server --port 8765
```

启动后访问 `http://127.0.0.1:8765/health` 验证存活。

## 3. 工作模式

sidecar 有两条工作路径，按以下条件自动选择：

| 条件 | 模式 | 行为 |
|---|---|---|
| `vendor/rvc/` 已 setup + `voice_id.pth` 存在 + `hubert_base.pt`/`rmvpe.pt` 存在 | **真实 RVC** | 完整 ContentVec + RMVPE + RVC + HiFiGAN |
| 其中任何一项缺失 | **回退 (pitch-shift)** | 用 `librosa.effects.pitch_shift` 仅做变调，方便先调通音频管线 |

切换是按 voice 切的：你可以一个音色用真实模型，另一个走 fallback。

## 4. 目录结构

```
sidecar/
├── pyproject.toml
├── requirements.txt
├── build_sidecar.py           # PyInstaller 打包入口
├── scripts/
│   └── setup_rvc.py           # 一键 setup
└── rvc_engine/
    ├── server.py              # FastAPI + WebSocket
    ├── pipeline.py            # 流式上下文管理 + 调度
    ├── feature_extract.py     # ContentVec / HuBERT
    ├── f0_extract.py          # RMVPE / FCPE / Crepe
    ├── inference.py           # RVC 真实推理（v1/v2 自适应）
    ├── sola.py                # SOLA 块拼接
    ├── vad.py                 # 静音检测
    ├── model_loader.py        # SHA256 校验
    ├── config.py              # 跨平台数据目录
    └── vendor/
        └── rvc/               # 由 setup_rvc.py 填充
            ├── infer_pack/{models,attentions,commons,modules,transforms}.py
            └── rmvpe.py
```

## 5. 协议

见仓库根目录 [`docs/PROTOCOL.md`](../docs/PROTOCOL.md)。

## 6. PyInstaller 打包

```bash
python build_sidecar.py
```

注意：打包前必须先运行 setup 脚本，让 vendor 文件就位，否则 PyInstaller 找不到 `rvc_engine.vendor.rvc.*`。
