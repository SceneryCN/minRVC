"""使用 PyInstaller 把 sidecar 打包为单文件可执行程序。

输出路径：`sidecar/dist/rvc-sidecar(.exe)`，
随后由 Tauri 的 externalBin 机制以 target-triple 命名拷贝到 `src-tauri/binaries/`。

打包前置条件：
- 必须先运行 `python -m scripts.setup_rvc`，否则 vendor 目录为空，
  PyInstaller 找不到 rvc_engine.vendor.rvc.*

用法：
    python build_sidecar.py
    python build_sidecar.py --debug
    python build_sidecar.py --onedir   # 输出目录而不是单文件，启动更快但分发文件多
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "rvc_engine" / "server.py"
VENDOR_DIR = ROOT / "rvc_engine" / "vendor" / "rvc"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
TAURI_BIN_DIR = ROOT.parent / "src-tauri" / "binaries"


def target_triple() -> str:
    """返回 Tauri 期望的 target triple，用于二进制重命名。"""
    sysname = platform.system().lower()
    arch = platform.machine().lower()
    if sysname == "windows":
        return "x86_64-pc-windows-msvc"
    if sysname == "darwin":
        return "aarch64-apple-darwin" if arch in ("arm64", "aarch64") else "x86_64-apple-darwin"
    return "x86_64-unknown-linux-gnu"


def ensure_vendor_ready() -> None:
    required = [
        VENDOR_DIR / "infer_pack" / "models.py",
        VENDOR_DIR / "infer_pack" / "commons.py",
        VENDOR_DIR / "rmvpe.py",
    ]
    missing = [p for p in required if not p.exists()]
    if missing:
        names = "\n    ".join(str(p.relative_to(ROOT)) for p in missing)
        print(
            "\n  vendor 目录不完整，请先运行：\n"
            "      python -m scripts.setup_rvc\n\n"
            f"  缺失文件：\n    {names}\n",
            file=sys.stderr,
        )
        sys.exit(2)


def build_pyinstaller_args(onefile: bool, debug: bool) -> list[str]:
    sep = ";" if platform.system() == "Windows" else ":"
    cmd: list[str] = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "rvc-sidecar",
        "--onefile" if onefile else "--onedir",
        "--console",
        # 把 vendor 目录整个收进来（PyInstaller 默认不会自动收集纯 .py 数据）
        "--add-data",
        f"{VENDOR_DIR}{sep}rvc_engine/vendor/rvc",
        # uvicorn 的隐式依赖
        "--collect-submodules",
        "uvicorn",
        # fairseq 极大量动态导入
        "--collect-submodules",
        "fairseq",
        "--collect-data",
        "fairseq",
        # torchaudio / torchcrepe 资源
        "--collect-data",
        "torchaudio",
        "--collect-data",
        "torchcrepe",
        # numpy 1.26 在 Windows 上的隐式 hook
        "--hidden-import",
        "numpy.core._methods",
        "--hidden-import",
        "numpy.lib.format",
        # rvc_engine 子包
        "--collect-submodules",
        "rvc_engine",
        str(ENTRY),
    ]
    if debug:
        cmd.append("--debug=all")
    return cmd


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--onedir", action="store_true", help="输出目录形式（启动更快）")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    if not ENTRY.exists():
        print(f"找不到入口 {ENTRY}", file=sys.stderr)
        sys.exit(2)

    ensure_vendor_ready()

    DIST.mkdir(exist_ok=True)
    BUILD.mkdir(exist_ok=True)

    cmd = build_pyinstaller_args(onefile=not args.onedir, debug=args.debug)
    print(">>>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=ROOT)

    triple = target_triple()
    src_name = "rvc-sidecar.exe" if platform.system() == "Windows" else "rvc-sidecar"
    src = DIST / src_name
    if not src.exists():
        # onedir 模式：产物在 dist/rvc-sidecar/
        candidate = DIST / "rvc-sidecar" / src_name
        if candidate.exists():
            src = candidate
        else:
            print(f"未找到产物 {src}", file=sys.stderr)
            sys.exit(3)

    TAURI_BIN_DIR.mkdir(parents=True, exist_ok=True)
    suffix = ".exe" if platform.system() == "Windows" else ""
    dst = TAURI_BIN_DIR / f"rvc-sidecar-{triple}{suffix}"
    shutil.copy2(src, dst)
    print(f"\n已拷贝到 {dst}")


if __name__ == "__main__":
    main()
