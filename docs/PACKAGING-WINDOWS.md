# Windows 打包指南

声变最终要分发给用户的形态是 **`.msi` 安装包**（或 `.exe` NSIS 安装器）。本文给两条路：

1. **本机 Windows 打包**（推荐做最终发布前的本地测试）
2. **GitHub Actions 远程打包**（推荐，不用买 Windows 机器）

---

## 0. 概念先对齐

打包 Windows 应用 = 打包 **三个东西**：

| 件 | 工具 | 产物 |
|---|---|---|
| 前端（React） | Vite | `dist/` 静态资源 |
| Rust 后端 + WebView shell | Tauri | `rvc-voice-changer.exe`（启动器） |
| Python 推理 sidecar | PyInstaller | `rvc-sidecar.exe`（独立进程） |

Tauri 把这三样统一塞进一个 `.msi` / `.exe` 安装器。

> **关键：PyInstaller 不能跨平台。** 在 macOS 上跑 PyInstaller 出来的是 macOS 二进制，**不是 Windows .exe**。所以打 Windows 包必须有 Windows 环境（本机 / VM / GitHub Actions）。

---

## 路线 A：本机 Windows 打包

### A.0 环境一次性准备（约 30 分钟）

| 软件 | 推荐版本 | 备注 |
|---|---|---|
| Windows 10 / 11 x64 | — | — |
| [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) | 2022 | 勾选 **「使用 C++ 的桌面开发」** |
| [Rust](https://rustup.rs/) | stable ≥ 1.77 | `rustup default stable` |
| [Node.js](https://nodejs.org/) | 20.x LTS | — |
| pnpm | 9.x | `corepack enable && corepack prepare pnpm@9 --activate` |
| [Python 3.11](https://python.org) | 3.10 / 3.11 | **不要用 3.12+**（`fairseq` 编不过） |
| [WiX Toolset 3](https://github.com/wixtoolset/wix3/releases) | 3.14 | Tauri 默认用它生成 `.msi` |
| [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) | latest | Win11 自带；Win10 需装 |

> Tauri 2 也支持 WiX 4，但 3 更稳定。

### A.1 拉代码 & 装依赖

```powershell
git clone https://github.com/<you>/RVC.git
cd RVC

# 前端
pnpm install

# Python sidecar 依赖（CPU 版 torch；GPU 用户本地再换 cu121）
cd sidecar
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 拉 RVC 上游源码 + 基础模型（hubert + rmvpe）
python -m scripts.setup_rvc
cd ..
```

### A.2 准备图标（已自带 placeholder）

```powershell
python scripts\generate_icons.py
```

发布前替换 `scripts/generate_icons.py` 里的 master 图为正式品牌图，再重跑此命令即可。

### A.3 一键打包

```powershell
pnpm bundle:windows
```

这条命令背后做了：

```
1. python build_sidecar.py
   → src-tauri/binaries/rvc-sidecar-x86_64-pc-windows-msvc.exe

2. tauri build --config src-tauri/tauri.bundle.conf.json --bundles msi,nsis
   → src-tauri/target/release/bundle/msi/声变_0.1.0_x64_zh-CN.msi
   → src-tauri/target/release/bundle/nsis/声变_0.1.0_x64-setup.exe
```

二选一分发：

- **`.msi`**：企业 / 商城渠道首选，支持 GPO 静默安装
- **`.exe` (NSIS)**：体积更小，普通用户更熟悉

### A.4 测试安装

双击 `.msi`，安装到 `C:\Program Files\声变\`。安装后：

```
C:\Program Files\声变\
├── 声变.exe                                    # Tauri 启动器
├── rvc-sidecar-x86_64-pc-windows-msvc.exe      # Python 推理 sidecar
├── WebView2Loader.dll
└── resources\
```

启动后第一次会走 `setup_rvc` 等价流程：用户需要单独把 `.pth` 模型导进来（首次启动会提示）。

---

## 路线 B：GitHub Actions（推荐）

不想买 Windows？不想配 VS Build Tools？让 CI 干。

### B.1 仓库准备

文件 `.github/workflows/release.yml` 已经写好（见仓库根）。它会：

| 触发 | 行为 |
|---|---|
| `workflow_dispatch`（手动点） | 在 Actions 页跑一遍，artifact 14 天可下 |
| `git push` 一个 `v0.1.0` 标签 | 跑一遍 + 自动建 GitHub Release（草稿） |

矩阵：

- `windows-latest` → `x86_64-pc-windows-msvc` → `.msi` + `.exe (NSIS)`
- `macos-14` (Apple Silicon) → `aarch64-apple-darwin` → `.dmg` + `.app`

### B.2 触发一次

```bash
# 手动触发
gh workflow run release.yml

# 或：打标签触发（推荐）
git tag v0.1.0
git push origin v0.1.0
```

### B.3 拿包

- 手动跑：Actions 页面 → 那次 run → Artifacts → 下载 `rvc-voice-changer-windows-x64.zip`
- 标签跑：GitHub Releases 页面 → 草稿 → 编辑后 Publish

### B.4 CI 比本机快多少？

| 阶段 | 本机 (M2 Mac) | CI (GitHub Actions Windows) |
|---|---|---|
| pnpm install | 25s | 60s |
| 装 PyTorch CPU | 60s | 120s |
| `cargo build --release`（首次） | 4min | 6min（缓存命中后 1min） |
| PyInstaller 打包 | 90s | 120s |
| Tauri bundle | 30s | 60s |
| **合计（首次）** | ≈ 7min | ≈ 11min |
| **合计（缓存）** | ≈ 3min | ≈ 4min |

CI 慢点但不用占本机。

---

## 常见坑

### 1. `setup_rvc` 在 GitHub Actions 拉不到模型

`hubert_base.pt` 和 `rmvpe.pt` 放在 HuggingFace。CI 拉不到的话，可以：

- a) 把模型上传到自己的 GitHub Release，CI 里改成从那里下
- b) 不打进安装包，用户首次启动后自动下载（当前架构已支持）

默认推荐 b），让安装包小（< 200MB），首次启动再补 ~ 350MB 模型。

### 2. `.msi` 里中文字符 / 安装路径乱码

WiX 3 默认 ASCII。在 `src-tauri/tauri.conf.json` 里：

```json
"bundle": {
  "windows": {
    "wix": {
      "language": ["zh-CN"]
    }
  }
}
```

并且确保 productName 里的「声变」用 UTF-8 保存（已经是）。

### 3. `WiX Toolset` 没装，打包报 `light.exe not found`

去 <https://github.com/wixtoolset/wix3/releases> 装 wix314.exe，重启 PowerShell 让 PATH 生效。

### 4. `fairseq` 在 Python 3.12 装不上

固定 Python 3.10 或 3.11。`pyenv install 3.11.10` 或者用官方安装器。

### 5. GPU vs CPU PyTorch

- CI 出包：CPU torch（小，~ 200MB）
- 用户拿到包后，**真正变声需要 NVIDIA GPU + CUDA 12.1**
- 安装后让用户跑：

```powershell
.\rvc-sidecar.exe --no-gpu  # 强制 CPU（仅调试音频管线）
```

或在应用内把 sidecar 的 `use_gpu` 关掉。

### 6. SmartScreen 警告 / 杀毒软件拦截

未签名的 `.exe` 在 Windows 10/11 上首次双击会触发 **「Windows 已保护你的电脑」**。两条路：

- a) 用户点「更多信息 → 仍要运行」
- b) 买 Authenticode 代码签名证书（~ ¥800/年）后在 CI 加签名步骤

学习用直接走 a）。商用必须 b）。

### 7. WebView2 在用户电脑上不存在

`tauri.conf.json` 已经设了：

```json
"windows": { "webviewInstallMode": { "type": "downloadBootstrapper" } }
```

意味着用户电脑没 WebView2 时会自动下载安装。Win11 自带；Win10 22H2+ 也自带；只有早期 Win10 才需要这个 fallback。

---

## 速查清单

```text
本机 Windows 一次性：
[ ] VS Build Tools 2022（C++ Desktop）
[ ] Rust stable
[ ] Node 20 + pnpm 9
[ ] Python 3.10/3.11
[ ] WiX Toolset 3.14
[ ] WebView2 Runtime（Win10 才需要）

每次出包：
[ ] git pull
[ ] pnpm install
[ ] cd sidecar && pip install -r requirements.txt && python -m scripts.setup_rvc && cd ..
[ ] python scripts/generate_icons.py（首次/换图后）
[ ] pnpm bundle:windows
[ ] 产物 → src-tauri/target/release/bundle/{msi,nsis}/

CI 出包：
[ ] git tag v0.1.0 && git push origin v0.1.0
[ ] Actions 跑完 → GitHub Release 草稿 → Publish
```
