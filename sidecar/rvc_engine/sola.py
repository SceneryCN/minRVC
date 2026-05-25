"""SOLA (Synchronized Overlap-Add) 块拼接。

实时变声以 chunk 为单位推理，块边界很容易出现相位不连续 / 咔嗒声。
SOLA 通过在 crossfade 区段内寻找最大互相关偏移，再做线性淡入淡出，
能显著消除毛刺。

参考：w-okada/voice-changer 的 sola.py。
"""

from __future__ import annotations

import numpy as np


class SOLAStitcher:
    def __init__(self, sample_rate: int, crossfade_time: float = 0.05) -> None:
        self.sample_rate = sample_rate
        self.crossfade_len = max(64, int(sample_rate * crossfade_time))
        self.search_len = self.crossfade_len // 2
        self.tail = np.zeros(0, dtype=np.float32)

    def process(self, chunk: np.ndarray) -> np.ndarray:
        chunk = np.asarray(chunk, dtype=np.float32).flatten()
        if self.tail.size == 0:
            # 第一块：留 crossfade 长度做 tail
            if chunk.size <= self.crossfade_len:
                self.tail = chunk.copy()
                return np.zeros(0, dtype=np.float32)
            head = chunk[: -self.crossfade_len]
            self.tail = chunk[-self.crossfade_len :].copy()
            return head

        # 在 chunk 起始 search_len 范围内寻找与 tail 的最大互相关
        if chunk.size < self.crossfade_len + self.search_len:
            # 块太短，简单覆盖
            merged = np.concatenate([self.tail, chunk])
            self.tail = np.zeros(0, dtype=np.float32)
            return merged

        cf = self.crossfade_len
        sl = self.search_len
        ref = self.tail
        win = chunk[: cf + sl]

        best = 0
        best_corr = -1.0
        for offset in range(sl + 1):
            seg = win[offset : offset + cf]
            num = float(np.dot(ref, seg))
            denom = float(np.linalg.norm(ref) * np.linalg.norm(seg)) + 1e-9
            corr = num / denom
            if corr > best_corr:
                best_corr = corr
                best = offset

        # 线性 crossfade
        fade_in = np.linspace(0.0, 1.0, cf, dtype=np.float32)
        fade_out = 1.0 - fade_in
        cross = ref * fade_out + chunk[best : best + cf] * fade_in

        # 输出：cross + 之后的部分（去掉新 tail）
        rest = chunk[best + cf :]
        if rest.size <= cf:
            self.tail = rest.copy()
            return cross
        out_main = rest[:-cf]
        self.tail = rest[-cf:].copy()
        return np.concatenate([cross, out_main])

    def reset(self) -> None:
        self.tail = np.zeros(0, dtype=np.float32)
