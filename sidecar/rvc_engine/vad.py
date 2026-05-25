"""非常简易的能量 VAD。

实时变声场景下 VAD 主要是为了静音段省 GPU，准确率要求不高。
后续可换成 silero-vad / webrtc-vad。
"""

from __future__ import annotations

import numpy as np


def simple_energy_vad(pcm: np.ndarray, threshold: float = 1e-3) -> bool:
    """True 表示「有声」，False 表示「静音」。

    threshold 是 RMS 阈值（线性幅度，1.0 = full-scale）。
    1e-3 ≈ -60dBFS，对一般人声足够保守。
    """
    if pcm.size == 0:
        return False
    rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float32))) + 1e-12))
    return rms > threshold
