"""Vendored RVC-Project sources. Run `python -m scripts.setup_rvc` to populate."""

from pathlib import Path as _Path

_THIS_DIR = _Path(__file__).resolve().parent
_REQUIRED = (
    "infer_pack/models.py",
    "infer_pack/commons.py",
    "rmvpe.py",
)


def is_populated() -> bool:
    """vendor 文件是否已就位。供 inference / f0 模块运行时检查。"""
    return all((_THIS_DIR / f).exists() for f in _REQUIRED)


def populate_hint() -> str:
    return (
        "RVC vendor 源码尚未下载。请先在 sidecar/ 目录运行：\n"
        "  python -m scripts.setup_rvc"
    )
