"""HuBERT / ContentVec 特征提取。

RVC 用的是 `lj1995/VoiceConversionWebUI/hubert_base.pt`，本质上是 fairseq 的
HubertModel checkpoint，输出第 9 / 12 层特征作为 RVC 的内容编码：
- v1 模型：取第 9 层，输出维度 256
- v2 模型：取第 12 层，输出维度 768

由于 fairseq 在新版 Python 上安装麻烦，我们做两层 fallback：
1. 主路径：fairseq.checkpoint_utils.load_model_ensemble_and_task —— 兼容性最好
2. 失败时 raise，让上层 pipeline.py 切到 stub 模式

线程安全：模型加载是一次性的，extract() 是无状态的（不持有 buffer）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from loguru import logger

FeatureLayer = Literal[9, 12]


class ContentVecExtractor:
    """ContentVec / HuBERT-base 特征提取器。"""

    def __init__(
        self,
        model_path: Path,
        device: str = "cuda",
        is_half: bool = True,
        layer: FeatureLayer = 12,
    ) -> None:
        self.model_path = Path(model_path)
        self.device = device
        self.is_half = is_half and device.startswith("cuda")
        self.layer = layer
        self._model = None
        self._task_cfg = None
        self._padding_mask = None

    def load(self) -> None:
        """加载 fairseq HuBERT 模型，必要时延迟到首次调用。"""
        if self._model is not None:
            return
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"找不到 ContentVec/HuBERT 权重: {self.model_path}\n"
                "请运行：cd sidecar && python -m scripts.setup_rvc"
            )

        try:
            import torch
            from fairseq import checkpoint_utils
        except ImportError as e:
            raise RuntimeError(
                "需要 fairseq 才能加载 ContentVec。"
                "在 Python 3.10/3.11 下执行：pip install fairseq==0.12.2"
            ) from e

        logger.info(f"加载 ContentVec: {self.model_path}")
        models, _saved_cfg, task_cfg = checkpoint_utils.load_model_ensemble_and_task(
            [str(self.model_path)],
            suffix="",
        )
        model = models[0]
        model = model.to(self.device)
        if self.is_half:
            model = model.half()
        else:
            model = model.float()
        model.eval()
        self._model = model
        self._task_cfg = task_cfg
        logger.info(f"ContentVec 就绪 device={self.device} half={self.is_half}")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def extract(self, pcm_16k: np.ndarray) -> "np.ndarray":
        """提取连续特征。

        Args:
            pcm_16k: 单声道 float32，采样率 16000Hz，shape [N]

        Returns:
            shape [T, D] 的 numpy 数组
            - v1 layer=9 -> D=256
            - v2 layer=12 -> D=768
            T ≈ N / 320（HuBERT 帧率 50Hz）
        """
        import torch

        if self._model is None:
            self.load()
        assert self._model is not None

        # 转 [1, N] tensor，类型与模型一致
        feats = torch.from_numpy(pcm_16k).to(self.device)
        feats = feats.half() if self.is_half else feats.float()
        if feats.dim() == 1:
            feats = feats.unsqueeze(0)
        # padding mask: 全 False（无 padding）
        if self._padding_mask is None or tuple(self._padding_mask.shape) != tuple(feats.shape):
            self._padding_mask = torch.zeros(
                feats.shape,
                dtype=torch.bool,
                device=feats.device,
            )
        inputs = {
            "source": feats,
            "padding_mask": self._padding_mask,
            "output_layer": self.layer,
        }
        with torch.no_grad():
            logits = self._model.extract_features(**inputs)
            # extract_features 返回 (x, _) 或 (x, _, _)；x shape [B, T, D]
            x = logits[0] if isinstance(logits, (list, tuple)) else logits
            # v1 模型在原 RVC 里需要 final_proj
            if self.layer == 9 and hasattr(self._model, "final_proj"):
                x = self._model.final_proj(x)
            x_np = x.squeeze(0).float().cpu().numpy()
        return x_np


# 兼容旧接口（pipeline.py 旧 stub）
class FeatureExtractor(ContentVecExtractor):
    """Backward-compatible alias."""

    def __init__(self, model_path: str, device: str = "cuda") -> None:
        super().__init__(Path(model_path), device=device, is_half=False, layer=12)
