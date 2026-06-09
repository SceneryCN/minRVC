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
import time
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
        self.index_rate: float = 0.5
        self.voice_thickness: float = 0.0
        self.rms_mix_rate: float = 0.25
        self.protect: float = 0.33
        self.loudness: float = 1.0
        self.f0_filter_radius: int = 3
        self.resample_sr: int = 0
        self.in_sr: int = 48_000
        self.out_sr: int = 48_000

        self._inferencer: Optional[RealRVCInferencer] = None
        self._sola: Optional[SOLAStitcher] = None
        self._history_16k = np.zeros(0, dtype=np.float32)
        self._last_profile: dict = {}
        self._profile_ema: dict[str, float] = {}

    # ---------- 控制面 ----------

    def prepare(
        self,
        voice_id: str,
        pitch: int,
        in_sr: int,
        out_sr: int,
        realtime_config: Optional[dict] = None,
    ) -> None:
        self.in_sr = in_sr
        self.out_sr = out_sr
        self.pitch_semitones = pitch
        self.set_realtime_config(realtime_config or {}, reload_f0=False)
        self.set_voice(voice_id)
        self._sola = SOLAStitcher(
            sample_rate=out_sr,
            crossfade_time=self.cfg.crossfade_time,
        )
        self._history_16k = np.zeros(0, dtype=np.float32)

    def set_voice(self, voice_id: str) -> None:
        self.current_voice_id = voice_id
        self._history_16k = np.zeros(0, dtype=np.float32)
        if self._sola is not None:
            self._sola.reset()
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
            self._inferencer.reset_stream()
            logger.info(f"voice={voice_id} 真实推理就绪")

    def set_pitch(self, semitones: int) -> None:
        self.pitch_semitones = max(-24, min(24, int(semitones)))

    def set_realtime_config(
        self,
        realtime_config: dict,
        reload_f0: bool = True,
    ) -> None:
        old_f0 = self.cfg.f0_method
        self.index_rate = max(
            0.0,
            min(1.0, float(realtime_config.get("indexRate", self.index_rate))),
        )
        self.voice_thickness = max(
            -1.0,
            min(
                1.0,
                float(realtime_config.get("voiceThickness", self.voice_thickness)),
            ),
        )
        self.loudness = max(
            0.0,
            min(2.0, float(realtime_config.get("loudness", self.loudness))),
        )
        self.rms_mix_rate = max(
            0.0,
            min(1.0, float(realtime_config.get("rmsMixRate", self.rms_mix_rate))),
        )
        self.protect = max(
            0.0,
            min(0.5, float(realtime_config.get("protect", self.protect))),
        )
        self.f0_filter_radius = max(
            0,
            min(7, int(realtime_config.get("f0FilterRadius", self.f0_filter_radius))),
        )
        self.resample_sr = int(realtime_config.get("resampleSr", self.resample_sr))
        if self.resample_sr not in (0, 16000, 32000, 40000, 44100, 48000):
            self.resample_sr = 0
        self.cfg.f0_method = str(realtime_config.get("f0Method", self.cfg.f0_method))
        self.cfg.crossfade_time = max(
            0.001,
            float(realtime_config.get("crossfadeMs", self.cfg.crossfade_time * 1000))
            / 1000.0,
        )
        self.cfg.extra_time = max(
            0.1,
            float(
                realtime_config.get(
                    "extraInferenceMs",
                    self.cfg.extra_time * 1000,
                )
            )
            / 1000.0,
        )
        if self._sola is not None:
            self._sola = SOLAStitcher(
                sample_rate=self.out_sr,
                crossfade_time=self.cfg.crossfade_time,
            )
        if self._inferencer is not None:
            self._inferencer.reset_stream()
        if reload_f0 and old_f0 != self.cfg.f0_method and self.current_voice_id:
            self.set_voice(self.current_voice_id)

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

    def profile(self) -> dict:
        return dict(self._last_profile)

    # ---------- 数据面 ----------

    def process(self, samples_in_sr: np.ndarray) -> Optional[np.ndarray]:
        """处理一个 chunk，返回输出 PCM（@out_sr，mono float32）。"""
        if samples_in_sr.size == 0:
            return None

        t_total = time.perf_counter()
        t = time.perf_counter()

        # 1) VAD：纯静音直接旁通静音，节省 GPU
        if not simple_energy_vad(samples_in_sr, threshold=1e-3):
            # 同步推进 history（重采样到 16k 后压入），保证恢复说话时上下文完整
            self._push_history(samples_in_sr)
            if self._inferencer is not None:
                self._inferencer.reset_stream()
            silent_out = np.zeros(
                int(samples_in_sr.shape[0] * self.out_sr / self.in_sr),
                dtype=np.float32,
            )
            self._update_profile(
                {
                    "vadMs": _elapsed_ms(t),
                    "totalMs": _elapsed_ms(t_total),
                    "mode": "silence",
                    "device": self.device,
                    "f0Method": self.cfg.f0_method,
                    "chunkSamples": int(samples_in_sr.shape[0]),
                }
            )
            return silent_out

        vad_ms = _elapsed_ms(t)
        t_infer = time.perf_counter()
        if self._inferencer is not None:
            out = self._infer_with_context(samples_in_sr)
            infer_profile = self._inferencer.last_profile.to_dict()
            mode = "rvc"
        else:
            out = self._fallback_pitch_shift(samples_in_sr)
            infer_profile = {}
            mode = "fallback"
        infer_ms = _elapsed_ms(t_infer)

        t_post = time.perf_counter()
        out = self._apply_voice_shape(out)

        if self.resample_sr > 0 and self.resample_sr != self.out_sr:
            out = _resample(out, self.out_sr, self.resample_sr)
            out = _resample(out, self.resample_sr, self.out_sr)
        post_ms = _elapsed_ms(t_post)

        # SOLA 拼接，消除块边界毛刺
        sola_ms = 0.0
        if self._sola is not None:
            t_sola = time.perf_counter()
            out = self._sola.process(out)
            sola_ms = _elapsed_ms(t_sola)
        profile = {
            **infer_profile,
            "vadMs": vad_ms,
            "pipelineInferMs": infer_ms,
            "postMs": post_ms,
            "solaMs": sola_ms,
            "totalMs": _elapsed_ms(t_total),
            "mode": mode,
            "device": self.device,
            "f0Method": self.cfg.f0_method,
            "chunkSamples": int(samples_in_sr.shape[0]),
        }
        self._update_profile(profile)
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

        audio_out = self._inferencer.infer_stream(
            pcm=samples_in_sr,
            in_sr=self.in_sr,
            out_sr=self.out_sr,
            pitch_semitones=self.pitch_semitones,
            index_rate=self.index_rate,
            rms_mix_rate=self.rms_mix_rate,
            protect=self.protect,
            f0_filter_radius=self.f0_filter_radius,
            context_seconds=self.cfg.extra_time,
        )
        return audio_out

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

    def _apply_voice_shape(self, pcm: np.ndarray) -> np.ndarray:
        out = pcm.astype(np.float32)
        if abs(self.voice_thickness) > 1e-3:
            out = self._shape_voice_tilt(out, float(self.voice_thickness))
        if abs(self.loudness - 1.0) > 1e-3:
            out = out * self.loudness
        return np.clip(out, -1.0, 1.0).astype(np.float32)

    @staticmethod
    def _shape_voice_tilt(pcm: np.ndarray, thickness: float) -> np.ndarray:
        """轻量声线塑形。

        实时链路不能在每个 chunk 后再跑一次 librosa pitch_shift；这里用三点低通
        得到粗略低频主体，再按方向做频谱倾斜：正值偏厚，负值偏亮。
        """
        if pcm.shape[0] < 3:
            return pcm
        amount = min(1.0, abs(thickness))
        low = np.empty_like(pcm)
        low[0] = pcm[0]
        low[-1] = pcm[-1]
        low[1:-1] = (pcm[:-2] + pcm[1:-1] * 2.0 + pcm[2:]) * 0.25
        high = pcm - low
        if thickness > 0:
            return pcm * (1.0 - 0.16 * amount) + low * (0.28 * amount)
        return pcm + high * (0.36 * amount)

    def _update_profile(self, profile: dict) -> None:
        alpha = 0.18
        smoothed: dict = {}
        for key, value in profile.items():
            if isinstance(value, (int, float)):
                old = self._profile_ema.get(key)
                new = float(value) if old is None else old * (1.0 - alpha) + float(value) * alpha
                self._profile_ema[key] = new
                smoothed[key] = round(new, 2)
            else:
                smoothed[key] = value
        self._last_profile = smoothed

    @staticmethod
    def _cuda_available() -> bool:
        try:
            import torch

            return bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            return False


def _elapsed_ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0
