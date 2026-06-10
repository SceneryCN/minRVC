"""一键下载 RVC 真实推理所需的全部资源。

完成 4 件事：
1. 从 RVC-Project 仓库 fetch 必要的源码到 `sidecar/vendor/rvc/`
2. 下载 ContentVec / HuBERT 基础模型 `hubert_base.pt`
3. 下载 RMVPE 基础模型 `rmvpe.pt`
4. 校验文件大小（不做 SHA256 强校验，避免上游版本变更频繁失败）

为什么不直接 git clone 上游仓库？
- vendor 进来的目录每个文件都要走 `python` 调用栈，clone 整个仓库会顺便引入
  一堆无关的 train/uvr5/i18n 资产（>200MB），对 sidecar 打包反而是负担
- 用户只需要前向推理代码，把它们「裁剪 vendor」是更干净的做法

模型权重统一放到 `~/AppData/Local/rvc-voice-changer/models/` (Windows)
或 `~/Library/Application Support/rvc-voice-changer/models/` (macOS)，
与 sidecar 运行时的 `SidecarConfig.models_dir` 严格一致。
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "rvc_engine" / "vendor" / "rvc"

RVC_RAW_BASE = (
    "https://raw.githubusercontent.com/"
    "RVC-Project/Retrieval-based-Voice-Conversion-WebUI/main"
)


@dataclass(frozen=True)
class VendorFile:
    """一份 vendor 文件的元信息。"""

    remote_path: str  # 相对 RVC-Project 仓库的路径
    local_path: str  # 相对 vendor/rvc/ 的路径
    min_size: int  # 字节，下载完成后做最低体积校验
    rewrite_imports: bool = True  # 是否需要把 `infer.lib.infer_pack` 重写成本地路径


VENDOR_FILES: tuple[VendorFile, ...] = (
    # SynthesizerTrn 与配套
    VendorFile("infer/lib/infer_pack/attentions.py", "infer_pack/attentions.py", 14_000),
    VendorFile("infer/lib/infer_pack/commons.py", "infer_pack/commons.py", 4_000),
    VendorFile("infer/lib/infer_pack/modules.py", "infer_pack/modules.py", 18_000),
    VendorFile("infer/lib/infer_pack/transforms.py", "infer_pack/transforms.py", 6_000),
    VendorFile("infer/lib/infer_pack/models.py", "infer_pack/models.py", 35_000),
    # F0 提取
    VendorFile("infer/lib/rmvpe.py", "rmvpe.py", 20_000),
)


@dataclass(frozen=True)
class WeightFile:
    """基础模型权重。"""

    name: str
    url: str
    relative_path: str  # 相对 models_dir/
    min_size: int


WEIGHTS: tuple[WeightFile, ...] = (
    WeightFile(
        name="hubert_base.pt (ContentVec)",
        url=(
            "https://huggingface.co/lj1995/VoiceConversionWebUI/"
            "resolve/main/hubert_base.pt"
        ),
        relative_path="hubert/hubert_base.pt",
        min_size=180_000_000,
    ),
    WeightFile(
        name="rmvpe.pt",
        url=(
            "https://huggingface.co/lj1995/VoiceConversionWebUI/"
            "resolve/main/rmvpe.pt"
        ),
        relative_path="rmvpe/rmvpe.pt",
        min_size=170_000_000,
    ),
)


# ---------- 工具函数 ----------

def _configure_stdio() -> None:
    """Windows CI consoles often default to cp1252; force UTF-8 for log output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _data_dir() -> Path:
    """与 sidecar/rvc_engine/config.py 的 _data_dir() 严格一致。"""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "rvc-voice-changer"


def _models_dir() -> Path:
    return _data_dir() / "models"


def _human(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


def _download(url: str, dst: Path, label: str) -> None:
    """带进度条的下载。失败时清理半成品文件。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    try:
        with urllib.request.urlopen(url) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            done = 0
            with tmp.open("wb") as f:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total > 0:
                        pct = done * 100 / total
                        sys.stdout.write(
                            f"\r[{label}] {_human(done)}/{_human(total)}  {pct:5.1f}%"
                        )
                    else:
                        sys.stdout.write(f"\r[{label}] {_human(done)}")
                    sys.stdout.flush()
        sys.stdout.write("\n")
        tmp.replace(dst)
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


def _rewrite_imports(text: str) -> str:
    """把 RVC-Project 仓库内部的绝对路径 import 改写到本地 vendor 命名空间。

    例：
        from infer.lib.infer_pack import commons
        ↓
        from rvc_engine.vendor.rvc.infer_pack import commons
    """
    replacements = [
        ("from infer.lib.infer_pack", "from rvc_engine.vendor.rvc.infer_pack"),
        ("import infer.lib.infer_pack", "import rvc_engine.vendor.rvc.infer_pack"),
        ("from infer.lib.rmvpe", "from rvc_engine.vendor.rvc.rmvpe"),
        ("import infer.lib.rmvpe", "import rvc_engine.vendor.rvc.rmvpe"),
        # rmvpe.py 里有时直接 `from lib.rmvpe import ...`，做兜底
        ("from lib.infer_pack", "from rvc_engine.vendor.rvc.infer_pack"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _ensure_init_files(targets: Iterable[Path]) -> None:
    """为 vendor 目录创建必要的 `__init__.py`。"""
    for path in targets:
        if path.is_dir():
            init_py = path / "__init__.py"
            if not init_py.exists():
                init_py.write_text("", encoding="utf-8")


# ---------- 主流程 ----------

def step_vendor_sources(force: bool) -> None:
    print(f"\n=== Step 1/2: vendor RVC 源码到 {VENDOR_DIR} ===")
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    for vf in VENDOR_FILES:
        dst = VENDOR_DIR / vf.local_path
        if dst.exists() and dst.stat().st_size >= vf.min_size and not force:
            print(f"  ✓ 跳过 {vf.local_path}（已存在 {_human(dst.stat().st_size)}）")
            continue
        url = f"{RVC_RAW_BASE}/{vf.remote_path}"
        _download(url, dst, vf.local_path)
        # 部分文件需要改写 import
        if vf.rewrite_imports:
            content = dst.read_text(encoding="utf-8")
            dst.write_text(_rewrite_imports(content), encoding="utf-8")
        if dst.stat().st_size < vf.min_size:
            raise RuntimeError(
                f"下载 {vf.local_path} 体积异常（{_human(dst.stat().st_size)}），"
                "可能上游已重构或网络问题，请重试或检查上游"
            )

    # 写入或刷新各级 __init__.py
    _ensure_init_files([VENDOR_DIR, VENDOR_DIR / "infer_pack"])

    # 顶层标识文件
    marker = VENDOR_DIR / "VENDOR_INFO.txt"
    marker.write_text(
        "Vendored from https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI\n"
        "License: MIT (上游仓库)\n"
        "Imports rewritten to `rvc_engine.vendor.rvc.*`\n",
        encoding="utf-8",
    )
    print("  ✓ vendor 源码完成")


def step_download_weights(force: bool, skip_weights: bool) -> None:
    print(f"\n=== Step 2/2: 下载基础模型权重到 {_models_dir()} ===")
    if skip_weights:
        print("  --skip-weights 已启用，跳过权重下载")
        return

    for w in WEIGHTS:
        dst = _models_dir() / w.relative_path
        if dst.exists() and dst.stat().st_size >= w.min_size and not force:
            print(f"  ✓ 跳过 {w.name}（已存在 {_human(dst.stat().st_size)}）")
            continue
        print(f"  ↓ 下载 {w.name}")
        _download(w.url, dst, dst.name)
        if dst.stat().st_size < w.min_size:
            raise RuntimeError(
                f"下载 {w.name} 体积过小（{_human(dst.stat().st_size)}），可能链接失效"
            )

    print("  ✓ 权重下载完成")


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="一键 setup RVC 真实推理资源（vendor 源码 + 基础模型权重）"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载已有文件",
    )
    parser.add_argument(
        "--skip-weights",
        action="store_true",
        help="只 vendor 源码，不下载模型权重（适合 CI / 离线分发）",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="删除 vendor/rvc 目录后重新开始",
    )
    args = parser.parse_args(argv)

    _configure_stdio()

    if args.clean and VENDOR_DIR.exists():
        print(f"清理 {VENDOR_DIR}")
        shutil.rmtree(VENDOR_DIR)

    try:
        step_vendor_sources(force=args.force)
        step_download_weights(force=args.force, skip_weights=args.skip_weights)
    except Exception as e:  # noqa: BLE001
        print(f"\nFailed: {e}", file=sys.stderr)
        return 1

    print(
        "\n全部完成 ✓\n"
        "下一步：把你的音色 .pth 模型放到\n"
        f"  {_models_dir() / 'voices'}/<voice_id>/<voice_id>.pth\n"
        "然后启动 sidecar：\n"
        "  python -m rvc_engine.server\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
