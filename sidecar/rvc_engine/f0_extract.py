"""F0 (基频) 提取。

支持 3 种算法：
- rmvpe: 推荐，对噪声鲁棒，速度也最快（vendor 自上游 RVC-Project）
- fcpe:  备用，CPU 友好（实现见 torchfcpe，运行时按需 import）
- crepe: 经典对照（torchcrepe）

设计原则：
- 模型实例可共享，f0 提取本身无状态
- 失败时清晰报错，让上层切到 fallback
- F0 → 索引转换（mel-scale 量化到 1..255）保留在这里，对齐 RVC 官方流程
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from loguru import logger

F0Method = Literal["rmvpe", "fcpe", "crepe"]


class F0Extractor:
    """对 RVC 官方 F0 流程的简化封装。"""

    def __init__(
        self,
        method: F0Method = "rmvpe",
        rmvpe_path: Path | None = None,
        device: str = "cuda",
        is_half: bool = True,
    ) -> None:
        self.method = method
        self.rmvpe_path = Path(rmvpe_path) if rmvpe_path else None
        self.device = device
        self.is_half = is_half and device.startswith("cuda")
        self._impl = None  # 懒加载

    # ---------- 加载 ----------

    def load(self) -> None:
        if self._impl is not None:
            return
        if self.method == "rmvpe":
            self._impl = self._load_rmvpe()
        elif self.method == "fcpe":
            self._impl = self._load_fcpe()
        elif self.method == "crepe":
            self._impl = self._load_crepe()
        else:
            raise ValueError(f"未知 F0 算法: {self.method}")

    def _load_rmvpe(self):
        if self.rmvpe_path is None or not self.rmvpe_path.exists():
            raise FileNotFoundError(
                f"找不到 RMVPE 权重: {self.rmvpe_path}\n"
                "请运行：cd sidecar && python -m scripts.setup_rvc"
            )
        try:
            from rvc_engine.vendor.rvc.rmvpe import RMVPE
        except ImportError as e:
            raise RuntimeError(
                "RMVPE 依赖 vendor/rvc/rmvpe.py。"
                "请运行：cd sidecar && python -m scripts.setup_rvc"
            ) from e
        logger.info(f"加载 RMVPE: {self.rmvpe_path}")
        return RMVPE(str(self.rmvpe_path), is_half=self.is_half, device=self.device)

    def _load_fcpe(self):
        try:
            from torchfcpe import spawn_bundled_infer_model
        except ImportError as e:
            raise RuntimeError("FCPE 需要 torchfcpe，pip install torchfcpe") from e
        logger.info("加载 FCPE")
        return spawn_bundled_infer_model(device=self.device)

    def _load_crepe(self):
        try:
            import torchcrepe  # noqa: F401
        except ImportError as e:
            raise RuntimeError("Crepe 需要 torchcrepe，pip install torchcrepe") from e
        logger.info("加载 Crepe (full)")
        return "torchcrepe"  # 占位，实际推理时按需调用

    # ---------- 推理 ----------

    def extract(
        self,
        pcm_16k: np.ndarray,
        f0_min: float = 50.0,
        f0_max: float = 1100.0,
        pitch_semitones: int = 0,
    ) -> tuple[np.ndarray, np.ndarray]:
        """提取 F0 + 离散索引。

        Args:
            pcm_16k:  shape [N]，16kHz 单声道 float32
            f0_min/max: 频率裁剪区间
            pitch_semitones: 半音变调

        Returns:
            (f0_coarse, f0_continuous)
            - f0_coarse:    np.int64, shape [T]，量化到 1..255 的索引
            - f0_continuous: np.float32, shape [T]，原始 F0（Hz）
        """
        if self._impl is None:
            self.load()

        if self.method == "rmvpe":
            f0 = self._impl.infer_from_audio(pcm_16k, thred=0.03)
        elif self.method == "fcpe":
            f0 = self._fcpe_infer(pcm_16k, f0_min, f0_max)
        else:
            f0 = self._crepe_infer(pcm_16k, f0_min, f0_max)

        # 应用变调
        if pitch_semitones != 0:
            f0 = f0 * (2.0 ** (pitch_semitones / 12.0))

        # 量化到 mel 索引
        f0_mel_min = 1127.0 * np.log(1.0 + f0_min / 700.0)
        f0_mel_max = 1127.0 * np.log(1.0 + f0_max / 700.0)
        f0_mel = 1127.0 * np.log(1.0 + f0 / 700.0)
        f0_mel = np.where(
            f0_mel > 0,
            (f0_mel - f0_mel_min) * 254 / (f0_mel_max - f0_mel_min) + 1,
            f0_mel,
        )
        f0_mel = np.clip(np.rint(f0_mel), 1, 255).astype(np.int64)
        return f0_mel, f0.astype(np.float32)

    def _fcpe_infer(self, pcm_16k: np.ndarray, f0_min: float, f0_max: float) -> np.ndarray:
        import torch

        with torch.no_grad():
            x = torch.from_numpy(pcm_16k).float().to(self.device).unsqueeze(0)
            f0 = self._impl.infer(
                x,
                sr=16000,
                decoder_mode="local_argmax",
                threshold=0.006,
                f0_min=f0_min,
                f0_max=f0_max,
                interp_uv=False,
                output_interp_target_length=None,
            )
        return f0.squeeze().cpu().numpy()

    def _crepe_infer(self, pcm_16k: np.ndarray, f0_min: float, f0_max: float) -> np.ndarray:
        import torch
        import torchcrepe

        x = torch.from_numpy(pcm_16k).float().to(self.device).unsqueeze(0)
        f0, pd = torchcrepe.predict(
            x,
            sample_rate=16000,
            hop_length=160,
            fmin=f0_min,
            fmax=f0_max,
            model="full",
            return_periodicity=True,
            device=self.device,
            pad=True,
        )
        # 用周期性置信度做无声判定
        f0 = torchcrepe.filter.median(f0, 3)
        pd = torchcrepe.filter.median(pd, 3)
        f0[pd < 0.1] = 0
        return f0.squeeze().cpu().numpy()
