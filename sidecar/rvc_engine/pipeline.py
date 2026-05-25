"""RVC 实时推理流水线（高层封装）。

数据流：
    incoming PCM (in_sr) ─► history_buf (16kHz)
                                       │
                                       ▼
                            [上下文 + 当前 chunk] ──► RealRVCInferencer
                                                          │
                                                          ▼
                                                   audio_out (out_sr)
                                                          │
                                                          ▼
                                                   只取最新 chunk 长度
                                                          │
                                                          ▼
                                              SOLAStitcher (块边界平滑)
                                                          │
                                                          ▼
                                                       outgoing PCM

两条路径：
1. 真实路径：当 voice_id 对应的 .pth + vendor 源码都就绪时，调用 RealRVCInferencer
2. 回退路径：模型缺失或加载失败时使用 librosa.effects.pitch_shift，至少把整条
   音频管线（设备 → 缓冲 → IPC → SOLA → 输出）跑通

线程模型：
- server.py 在 asyncio.to_thread 里同步调用 process()，所以 process() 必须线程安全
  且无并发要求。本类持有的 history_buf / SOLA 状态因此天然单线程访问，无需锁。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import numpy as np
from loguru import logger

from .config import SidecarConfig
from .inference import RealRVCInferencer, _resample
from .sola import SOLAStitcher
from .vad import simple_energy_vad


class RVCPipeline:
    """实时推理流水线。"""

    def __init__(self, cfg: SidecarConfig) -> None:
        self.cfg = cfg
        self.device = "cuda" if cfg.use_gpu and self._cuda_available() else "cpu"
        if cfg.use_gpu and self.device == "cpu":
            logger.warning("未检测到 CUDA，回退到 CPU（实时性能可能不足）")

        self.current_voice_id: Optional[str] = None
        self.pitch_semitones: int = 0
        self.in_sr: int = 48_000
        self.out_sr: int = 48_000

        self._inferencer: Optional[RealRVCInferencer] = None
        self._sola: Optional[SOLAStitcher] = None
        self._history_16k = np.zeros(0, dtype=np.float32)

    # ---------- 控制面 ----------

    def prepare(self, voice_id: str, pitch: int, in_sr: int, out_sr: int) -> None:
        self.in_sr = in_sr
        self.out_sr = out_sr
        self.pitch_semitones = pitch
        self.set_voice(voice_id)
        self._sola = SOLAStitcher(
            sample_rate=out_sr,
            crossfade_time=self.cfg.crossfade_time,
        )
        self._history_16k = np.zeros(0, dtype=np.float32)

    def set_voice(self, voice_id: str) -> None:
        self.current_voice_id = voice_id
        pth = self.cfg.voices_dir / voice_id / f"{voice_id}.pth"
        if not pth.exists():
            logger.warning(
                f"voice_id={voice_id} 没有 .pth 模型，使用回退（音高变换）模式。"
                f" 请将文件放到 {pth}"
            )
            self._inferencer = None
            return
        self._inferencer = RealRVCInferencer(
            cfg=self.cfg,
            voice_id=voice_id,
            pth_path=pth,
            index_path=self._maybe_index(voice_id),
            device=self.device,
        )
        if not self._inferencer.ready:
            logger.warning(f"voice_id={voice_id} 模型加载失败，使用回退模式")
            self._inferencer = None
        else:
            logger.info(f"voice={voice_id} 真实推理就绪")

    def set_pitch(self, semitones: int) -> None:
        self.pitch_semitones = max(-24, min(24, int(semitones)))

    def list_voices(self) -> List[dict]:
        out: List[dict] = []
        if not self.cfg.voices_dir.exists():
            return out
        for d in sorted(self.cfg.voices_dir.iterdir()):
            if not d.is_dir():
                continue
            pth = d / f"{d.name}.pth"
            out.append(
                {
                    "id": d.name,
                    "installed": pth.exists(),
                    "path": str(pth) if pth.exists() else None,
                }
            )
        return out

    # ---------- 数据面 ----------

    def process(self, samples_in_sr: np.ndarray) -> Optional[np.ndarray]:
        """处理一个 chunk，返回输出 PCM（@out_sr，mono float32）。"""
        if samples_in_sr.size == 0:
            return None

        # 1) VAD：纯静音直接旁通静音，节省 GPU
        if not simple_energy_vad(samples_in_sr, threshold=1e-3):
            # 同步推进 history（重采样到 16k 后压入），保证恢复说话时上下文完整
            self._push_history(samples_in_sr)
            silent_out = np.zeros(
                int(samples_in_sr.shape[0] * self.out_sr / self.in_sr),
                dtype=np.float32,
            )
            return silent_out

        if self._inferencer is not None:
            out = self._infer_with_context(samples_in_sr)
        else:
            out = self._fallback_pitch_shift(samples_in_sr)

        # SOLA 拼接，消除块边界毛刺
        if self._sola is not None:
            out = self._sola.process(out)
        return out

    # ---------- 内部 ----------

    def _maybe_index(self, voice_id: str) -> Optional[Path]:
        idx = self.cfg.voices_dir / voice_id / f"{voice_id}.index"
        return idx if idx.exists() else None

    def _push_history(self, samples_in_sr: np.ndarray) -> None:
        """把当前 chunk 重采样到 16k 后追加到 history_16k，截断超长部分。"""
        chunk_16k = (
            _resample(samples_in_sr, self.in_sr, 16_000)
            if self.in_sr != 16_000
            else samples_in_sr.astype(np.float32)
        )
        max_len = int(self.cfg.extra_time * 16_000)
        merged = np.concatenate([self._history_16k, chunk_16k])
        if merged.shape[0] > max_len:
            merged = merged[-max_len:]
        self._history_16k = merged

    def _infer_with_context(self, samples_in_sr: np.ndarray) -> np.ndarray:
        """带上下文的流式 RVC 推理。

        关键技巧：
        - 把当前 chunk 拼到 history_16k 末尾，整段送进 RealRVCInferencer
        - 推理输出可能跨越上下文 + 当前 chunk，最后只截取「当前 chunk 对应的尾部」
        - 长度不够时返回静音 chunk 做 padding（用户基本感知不到）
        """
        assert self._inferencer is not None

        prev_history_len = self._history_16k.shape[0]
        self._push_history(samples_in_sr)
        current_chunk_len_16k = self._history_16k.shape[0] - prev_history_len

        # 整段（含上下文）送进推理
        audio_out = self._inferencer.infer(
            pcm=self._history_16k,
            in_sr=16_000,
            out_sr=self.out_sr,
            pitch_semitones=self.pitch_semitones,
        )

        # 估算「当前 chunk」对应输出长度
        out_per_in = self.out_sr / 16_000
        target_out_len = int(round(current_chunk_len_16k * out_per_in))

        if audio_out.shape[0] < target_out_len:
            pad = target_out_len - audio_out.shape[0]
            audio_out = np.concatenate([audio_out, np.zeros(pad, dtype=np.float32)])
        # 取尾部（最新生成的部分），其余是上下文产物
        return audio_out[-target_out_len:]

    def _fallback_pitch_shift(self, pcm: np.ndarray) -> np.ndarray:
        """没有 RVC 模型时的占位实现：仅按 pitch_semitones 做 phase-vocoder 变调。"""
        # 即使是 fallback，也维护 history 让真实模型恢复加载时上下文不丢
        self._push_history(pcm)

        if self.pitch_semitones == 0:
            # 也要做 sr 转换
            return (
                _resample(pcm, self.in_sr, self.out_sr)
                if self.in_sr != self.out_sr
                else pcm.astype(np.float32)
            )
        try:
            import librosa  # 延迟导入

            shifted = librosa.effects.pitch_shift(
                pcm.astype(np.float32),
                sr=self.in_sr,
                n_steps=float(self.pitch_semitones),
            )
            if self.in_sr != self.out_sr:
                shifted = _resample(shifted, self.in_sr, self.out_sr)
            return shifted.astype(np.float32)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"pitch_shift 失败，原样返回: {e}")
            return pcm.astype(np.float32)

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            return False
