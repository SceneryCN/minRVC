"""sidecar 全局配置。

注意：所有路径均通过环境变量或默认 `~/AppData/Local/rvc-voice-changer/` 解析，
保持与 Tauri Rust 端 `dirs::data_local_dir()` 一致。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    p = base / "rvc-voice-changer"
    p.mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class SidecarConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    data_dir: Path = field(default_factory=_data_dir)

    target_sr: int = 16_000  # HuBERT 输入采样率
    block_time: float = 0.25  # 每次推理处理 0.25s 音频
    crossfade_time: float = 0.01  # SOLA 交叉淡化时长
    extra_time: float = 2.5  # 历史上下文（秒），减小不连续感

    f0_method: str = "rmvpe"  # rmvpe / fcpe / crepe
    use_gpu: bool = True
    device: str = "cuda"  # 启动时再校正

    @property
    def models_dir(self) -> Path:
        d = self.data_dir / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def voices_dir(self) -> Path:
        d = self.models_dir / "voices"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def hubert_dir(self) -> Path:
        d = self.models_dir / "hubert"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def rmvpe_dir(self) -> Path:
        d = self.models_dir / "rmvpe"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def separation_dir(self) -> Path:
        """离线人声分离输出目录。"""
        d = self.data_dir / "separation"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def training_dir(self) -> Path:
        """本机训练任务输出目录。"""
        d = self.data_dir / "training"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def demucs_models_dir(self) -> Path:
        """Demucs 预训练模型缓存目录（torch.hub 默认放这里）。"""
        d = self.models_dir / "demucs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def audio_separator_models_dir(self) -> Path:
        """audio-separator / UVR 系模型缓存目录。"""
        d = self.models_dir / "audio-separator"
        d.mkdir(parents=True, exist_ok=True)
        return d
