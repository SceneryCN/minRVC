# vendor/

第三方代码 vendor 目录。**不要手动修改这里的文件**，全部由 setup 脚本管理。

## rvc/

来源：[RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)（MIT License）

裁剪后的最小子集，仅保留前向推理需要的文件：

```
rvc/
├── __init__.py
├── VENDOR_INFO.txt
├── infer_pack/
│   ├── __init__.py
│   ├── attentions.py
│   ├── commons.py
│   ├── modules.py
│   ├── transforms.py
│   └── models.py        # SynthesizerTrnMs256NSFsid v1/v2
└── rmvpe.py             # F0 提取模型
```

## 如何获取

```bash
cd sidecar
python -m scripts.setup_rvc
```

或单独 vendor（不下载基础模型权重）：

```bash
python -m scripts.setup_rvc --skip-weights
```

强制重新下载：

```bash
python -m scripts.setup_rvc --force --clean
```

## 升级策略

上游 RVC-Project 偶尔会重命名 / 重构 `infer/lib/`。如果 vendor 失败：
1. 检查 `sidecar/scripts/setup_rvc.py` 的 `VENDOR_FILES` 列表
2. 对比上游最新文件路径，更新 `remote_path`
3. 重跑 `python -m scripts.setup_rvc --clean`

## 为什么不直接 git submodule？

- submodule 把整仓库（含 train / uvr5 / 数据集脚本）一起拉进来，>200MB
- PyInstaller 打包时也得排除 submodule 的非必要文件，复杂度高
- 我们只需要 6 个 .py 文件做前向推理，vendor 后体积 ~120KB
