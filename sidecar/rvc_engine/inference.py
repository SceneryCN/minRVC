"""真实 RVC 推理器。

职责：
- 加载 .pth 检查点，自适应 v1（256 维）/ v2（768 维）+ NSF / NSFsid_nono 等架构
- 调用 ContentVecExtractor + F0Extractor 得到中间表示
- （可选）用 Faiss 索引做检索增强
- 调用 SynthesizerTrn 生成 .target_sr 的输出 PCM

参考：
- vendor/rvc/infer_pack/models.py 中的 SynthesizerTrnMs256NSFsid / SynthesizerTrnMs768NSFsid
- 上游 infer/lib/rtrvc.py（实时推理流水线）

线程安全：单实例不要跨线程并发 infer()。pipeline.py 会保证串行。
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

from .config import SidecarConfig
from .feature_extract import ContentVecExtractor
from .f0_extract import F0Extractor


@dataclass
class _ModelMeta:
    """从 .pth checkpoint 推断出的模型元信息。"""

    target_sr: int
    if_f0: bool  # 是否带 F0 输入（绝大多数 RVC 都是 True）
    version: str  # "v1" / "v2"
    feature_dim: int  # 256 / 768
    n_speakers: int


class RealRVCInferencer:
    """真实 RVC 推理器（v1/v2 兼容）。

    使用方式：
        inf = RealRVCInferencer(cfg, voice_id, pth_path, index_path, device)
        if inf.ready:
            audio = inf.infer(pcm, in_sr, out_sr, pitch_semitones)
    """

    def __init__(
        self,
        cfg: SidecarConfig,
        voice_id: str,
        pth_path: Path,
        index_path: Optional[Path],
        device: str,
    ) -> None:
        self.cfg = cfg
        self.voice_id = voice_id
        self.pth_path = Path(pth_path)
        self.index_path = Path(index_path) if index_path else None
        self.device = device
        self.is_half = device.startswith("cuda")

        self.meta: Optional[_ModelMeta] = None
        self._net_g = None
        self._faiss_index = None
        self._big_npy = None  # 索引检索时使用的特征矩阵
        self._content_vec: Optional[ContentVecExtractor] = None
        self._f0: Optional[F0Extractor] = None
        self._loaded = False
        self._stream_tail_16k = np.zeros(0, dtype=np.float32)
        self._stream_source_16k = np.zeros(0, dtype=np.float32)
        self._stream_feats: Optional[np.ndarray] = None
        self._stream_pitch: Optional[np.ndarray] = None
        self._stream_pitchf: Optional[np.ndarray] = None
        self._supports_stream_decode = False

        try:
            self._load_all()
            self._loaded = True
        except Exception as e:  # noqa: BLE001
            logger.exception(f"RVC 模型加载失败 ({pth_path}): {e}")

    # ---------- 加载 ----------

    @property
    def ready(self) -> bool:
        return self._loaded

    @property
    def target_sr(self) -> int:
        return self.meta.target_sr if self.meta else 40_000

    def reset_stream(self) -> None:
        """清空流式缓存。

        音色、音高算法、检索比例或 F0 保护参数变化后，旧缓存对应的特征不再可靠。
        """
        self._stream_tail_16k = np.zeros(0, dtype=np.float32)
        self._stream_source_16k = np.zeros(0, dtype=np.float32)
        self._stream_feats = None
        self._stream_pitch = None
        self._stream_pitchf = None

    def _load_all(self) -> None:
        from rvc_engine.vendor import rvc as rvc_pkg

        if not rvc_pkg.is_populated():
            raise RuntimeError(rvc_pkg.populate_hint())

        self._load_generator()
        self._load_optional_index()
        self._load_content_vec()
        self._load_f0()

    def _load_generator(self) -> None:
        """从 .pth 检查点反推架构并加载权重。"""
        import torch

        ckpt = torch.load(self.pth_path, map_location="cpu")
        if "config" not in ckpt or "weight" not in ckpt:
            raise RuntimeError(
                f"{self.pth_path} 不是有效的 RVC 推理 checkpoint（缺 config/weight 字段）"
            )

        cfg_list = ckpt["config"]
        target_sr = int(ckpt.get("sr", cfg_list[-1] if isinstance(cfg_list[-1], int) else 40_000))
        if_f0 = bool(ckpt.get("f0", 1))
        version = str(ckpt.get("version", "v1"))
        feature_dim = 768 if version == "v2" else 256
        n_speakers = int(cfg_list[-3]) if len(cfg_list) >= 3 else 109

        self.meta = _ModelMeta(
            target_sr=target_sr,
            if_f0=if_f0,
            version=version,
            feature_dim=feature_dim,
            n_speakers=n_speakers,
        )
        logger.info(
            f"RVC ckpt: {self.pth_path.name} version={version} sr={target_sr} "
            f"f0={if_f0} feat_dim={feature_dim}"
        )

        # 选 SynthesizerTrn 类
        from rvc_engine.vendor.rvc.infer_pack.models import (  # type: ignore
            SynthesizerTrnMs256NSFsid,
            SynthesizerTrnMs256NSFsid_nono,
            SynthesizerTrnMs768NSFsid,
            SynthesizerTrnMs768NSFsid_nono,
        )

        if version == "v1":
            cls = SynthesizerTrnMs256NSFsid if if_f0 else SynthesizerTrnMs256NSFsid_nono
        else:
            cls = SynthesizerTrnMs768NSFsid if if_f0 else SynthesizerTrnMs768NSFsid_nono

        net_g = cls(*cfg_list, is_half=self.is_half)
        # 移除 enc_q（训练用，推理不需要，删掉省内存）
        if hasattr(net_g, "enc_q"):
            del net_g.enc_q
        net_g.load_state_dict(ckpt["weight"], strict=False)
        net_g.eval().to(self.device)
        net_g = net_g.half() if self.is_half else net_g.float()
        self._net_g = net_g
        self._supports_stream_decode = _supports_stream_decode(net_g)
        logger.info(f"RVC Generator realtime crop={self._supports_stream_decode}")

    def _load_optional_index(self) -> None:
        if self.index_path is None or not self.index_path.exists():
            logger.info(f"voice={self.voice_id} 无 .index，跳过检索增强")
            return
        try:
            import faiss
        except ImportError:
            logger.warning("faiss 未安装，跳过检索增强（pip install faiss-cpu）")
            return
        try:
            index = faiss.read_index(str(self.index_path))
            big_npy = index.reconstruct_n(0, index.ntotal)
            self._faiss_index = index
            self._big_npy = big_npy
            logger.info(f"Faiss 索引就绪: ntotal={index.ntotal}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Faiss 索引加载失败，跳过检索: {e}")

    def _load_content_vec(self) -> None:
        path = self.cfg.hubert_dir / "hubert_base.pt"
        layer = 12 if (self.meta and self.meta.version == "v2") else 9
        self._content_vec = ContentVecExtractor(
            model_path=path,
            device=self.device,
            is_half=self.is_half,
            layer=layer,
        )
        self._content_vec.load()

    def _load_f0(self) -> None:
        if self.meta is None or not self.meta.if_f0:
            return
        rmvpe_path = self.cfg.rmvpe_dir / "rmvpe.pt"
        self._f0 = F0Extractor(
            method=self.cfg.f0_method,  # type: ignore[arg-type]
            rmvpe_path=rmvpe_path,
            device=self.device,
            is_half=self.is_half,
        )
        self._f0.load()

    # ---------- 推理 ----------

    def infer(
        self,
        pcm: np.ndarray,
        in_sr: int,
        out_sr: int,
        pitch_semitones: int,
        index_rate: float = 0.5,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        f0_filter_radius: int = 3,
    ) -> np.ndarray:
        """对一段已经包含足够上下文的 PCM 做 RVC 推理。

        约定：调用方（pipeline.py）已经把上下文拼接好；本方法不维护跨调用状态。
        """
        if not self._loaded or self.meta is None or self._net_g is None:
            return self._fallback_pitch_shift(pcm, in_sr, pitch_semitones)

        # 1) 重采样到 16kHz 给 ContentVec / RMVPE 用
        pcm_16k = _resample(pcm, in_sr, 16_000) if in_sr != 16_000 else pcm
        pcm_16k = pcm_16k.astype(np.float32)

        feats = self._extract_indexed_features(pcm_16k, index_rate)
        if self.meta.if_f0:
            pitch, pitchf = self._extract_f0(
                pcm_16k,
                pitch_semitones=pitch_semitones,
                filter_radius=f0_filter_radius,
                protect=protect,
            )
        else:
            pitch = pitchf = None

        audio_np = self._synthesize_from_features(feats, pitch, pitchf, out_sr)

        if 0.0 < rms_mix_rate < 1.0:
            audio_np = _apply_rms_mix(audio_np, pcm, in_sr, out_sr, rms_mix_rate)

        return audio_np

    def infer_stream(
        self,
        pcm: np.ndarray,
        in_sr: int,
        out_sr: int,
        pitch_semitones: int,
        index_rate: float = 0.5,
        rms_mix_rate: float = 0.25,
        protect: float = 0.33,
        f0_filter_radius: int = 3,
        context_seconds: float = 2.5,
        overlap_seconds: float = 0.32,
    ) -> np.ndarray:
        """缓存式流式推理。

        只对新 chunk 加少量左侧重叠重新提取 ContentVec/F0，旧帧从缓存中取。
        Generator 使用 RVC 官方 realtime infer 暴露的 skip_head/return_length
        只返回新 chunk 对应的音频；旧版 vendor 不支持该签名时自动回退整段窗口解码。
        """
        if not self._loaded or self.meta is None or self._net_g is None:
            return self._fallback_pitch_shift(pcm, in_sr, pitch_semitones)

        pcm_16k = _resample(pcm, in_sr, 16_000) if in_sr != 16_000 else pcm
        pcm_16k = pcm_16k.astype(np.float32)
        if pcm_16k.size == 0:
            return np.zeros(0, dtype=np.float32)

        prefix = self._stream_tail_16k
        compute_pcm = (
            np.concatenate([prefix, pcm_16k]) if prefix.size else pcm_16k
        ).astype(np.float32)

        feats_compute = self._extract_indexed_features(compute_pcm, index_rate)
        new_feat_count = _estimate_tail_count(
            total_count=feats_compute.shape[0],
            total_samples=compute_pcm.shape[0],
            new_samples=pcm_16k.shape[0],
        )
        new_feats = feats_compute[-new_feat_count:]

        if self.meta.if_f0:
            pitch_compute, pitchf_compute = self._extract_f0(
                compute_pcm,
                pitch_semitones=pitch_semitones,
                filter_radius=f0_filter_radius,
                protect=protect,
            )
            new_pitch_count = _estimate_tail_count(
                total_count=pitch_compute.shape[0],
                total_samples=compute_pcm.shape[0],
                new_samples=pcm_16k.shape[0],
            )
            new_pitch = pitch_compute[-new_pitch_count:]
            new_pitchf = pitchf_compute[-new_pitch_count:]
        else:
            new_pitch = new_pitchf = None

        max_feat_frames = max(4, int(max(0.1, context_seconds) * 50))
        max_pitch_frames = max(8, int(max(0.1, context_seconds) * 100))
        self._stream_feats = _append_frames(self._stream_feats, new_feats, max_feat_frames)
        if self.meta.if_f0 and new_pitch is not None and new_pitchf is not None:
            self._stream_pitch = _append_frames(
                self._stream_pitch,
                new_pitch.astype(np.int64),
                max_pitch_frames,
            )
            self._stream_pitchf = _append_frames(
                self._stream_pitchf,
                new_pitchf.astype(np.float32),
                max_pitch_frames,
            )

        max_source_samples = max(1600, int(max(0.1, context_seconds) * 16_000))
        self._stream_source_16k = _append_audio(
            self._stream_source_16k,
            pcm_16k,
            max_source_samples,
        )
        max_overlap = max(0, int(max(0.0, overlap_seconds) * 16_000))
        self._stream_tail_16k = (
            compute_pcm[-max_overlap:].copy() if max_overlap > 0 else np.zeros(0, dtype=np.float32)
        )

        if self._stream_feats is None or self._stream_feats.size == 0:
            return np.zeros(int(round(pcm_16k.shape[0] * out_sr / 16_000)), dtype=np.float32)

        audio_np = self._synthesize_from_features(
            self._stream_feats,
            self._stream_pitch if self.meta.if_f0 else None,
            self._stream_pitchf if self.meta.if_f0 else None,
            out_sr,
            tail_frames_100hz=(
                new_pitch.shape[0]
                if self.meta.if_f0 and new_pitch is not None
                else new_feats.shape[0] * 2
            ),
        )

        if 0.0 < rms_mix_rate < 1.0:
            audio_np = _apply_rms_mix(
                audio_np,
                self._stream_source_16k,
                16_000,
                out_sr,
                rms_mix_rate,
            )

        target_out_len = int(round(pcm_16k.shape[0] * out_sr / 16_000))
        if audio_np.shape[0] < target_out_len:
            audio_np = np.concatenate(
                [audio_np, np.zeros(target_out_len - audio_np.shape[0], dtype=np.float32)]
            )
        return audio_np[-target_out_len:]

    def _extract_indexed_features(
        self,
        pcm_16k: np.ndarray,
        index_rate: float,
    ) -> np.ndarray:
        assert self._content_vec is not None
        feats = self._content_vec.extract(pcm_16k).astype(np.float32)
        if self._faiss_index is None or self._big_npy is None or index_rate <= 0:
            return feats
        try:
            _, ix = self._faiss_index.search(feats, k=8)
            weights = np.square(
                1
                / (
                    np.linalg.norm(
                        self._big_npy[ix] - feats[:, None],
                        axis=-1,
                    )
                    + 1e-8
                )
            )
            weights /= weights.sum(axis=-1, keepdims=True)
            searched = (
                self._big_npy[ix] * np.expand_dims(weights, axis=-1)
            ).sum(axis=-2)
            return ((1 - index_rate) * feats + index_rate * searched).astype(np.float32)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Faiss 检索失败，跳过: {e}")
            return feats

    def _extract_f0(
        self,
        pcm_16k: np.ndarray,
        pitch_semitones: int,
        filter_radius: int,
        protect: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        assert self._f0 is not None
        return self._f0.extract(
            pcm_16k,
            pitch_semitones=pitch_semitones,
            filter_radius=filter_radius,
            protect=protect,
        )

    def _synthesize_from_features(
        self,
        feats: np.ndarray,
        pitch: Optional[np.ndarray],
        pitchf: Optional[np.ndarray],
        out_sr: int,
        tail_frames_100hz: Optional[int] = None,
    ) -> np.ndarray:
        assert self.meta is not None and self._net_g is not None
        if feats.size == 0:
            return np.zeros(0, dtype=np.float32)

        import torch

        feats_t = torch.from_numpy(feats.astype(np.float32)).to(self.device)
        feats_t = feats_t.half() if self.is_half else feats_t.float()
        feats_t = feats_t.unsqueeze(0)
        feats_t = torch.nn.functional.interpolate(
            feats_t.permute(0, 2, 1), scale_factor=2
        ).permute(0, 2, 1)
        t_feats = feats_t.shape[1]

        if self.meta.if_f0:
            if pitch is None or pitchf is None:
                pitch = np.ones(t_feats, dtype=np.int64)
                pitchf = np.zeros(t_feats, dtype=np.float32)
            pitch = _align_length(pitch, t_feats)
            pitchf = _align_length(pitchf, t_feats)
            pitch_t = torch.from_numpy(pitch).to(self.device).long().unsqueeze(0)
            pitchf_t = torch.from_numpy(pitchf).to(self.device)
            pitchf_t = pitchf_t.half() if self.is_half else pitchf_t.float()
            pitchf_t = pitchf_t.unsqueeze(0)
        else:
            pitch_t = pitchf_t = None

        sid_t = torch.tensor([0], device=self.device).long()
        feats_len_t = torch.tensor([t_feats], device=self.device).long()
        skip_head_t = return_length_t = return_length2_t = None
        if tail_frames_100hz is not None and self._supports_stream_decode:
            return_len = max(1, min(t_feats, int(tail_frames_100hz)))
            skip_head = max(0, t_feats - return_len)
            skip_head_t = torch.tensor(skip_head, device=self.device).long()
            return_length_t = torch.tensor(return_len, device=self.device).long()
            return_length2_t = torch.tensor(return_len, device=self.device).long()

        with torch.no_grad():
            if self.meta.if_f0:
                if skip_head_t is not None:
                    try:
                        audio = self._net_g.infer(
                            feats_t,
                            feats_len_t,
                            pitch_t,
                            pitchf_t,
                            sid_t,
                            skip_head_t,
                            return_length_t,
                            return_length2_t,
                        )[0][0, 0]
                    except TypeError as e:
                        logger.warning(f"Generator 不支持 realtime crop，回退整段解码: {e}")
                        self._supports_stream_decode = False
                        audio = self._net_g.infer(
                            feats_t,
                            feats_len_t,
                            pitch_t,
                            pitchf_t,
                            sid_t,
                        )[0][0, 0]
                else:
                    audio = self._net_g.infer(
                        feats_t,
                        feats_len_t,
                        pitch_t,
                        pitchf_t,
                        sid_t,
                    )[0][0, 0]
            else:
                if skip_head_t is not None:
                    try:
                        audio = self._net_g.infer(
                            feats_t,
                            feats_len_t,
                            sid_t,
                            skip_head_t,
                            return_length_t,
                            return_length2_t,
                        )[0][0, 0]
                    except TypeError as e:
                        logger.warning(f"Generator 不支持 realtime crop，回退整段解码: {e}")
                        self._supports_stream_decode = False
                        audio = self._net_g.infer(
                            feats_t,
                            feats_len_t,
                            sid_t,
                        )[0][0, 0]
                else:
                    audio = self._net_g.infer(
                        feats_t,
                        feats_len_t,
                        sid_t,
                    )[0][0, 0]
        audio_np = audio.float().cpu().numpy().astype(np.float32)
        if self.meta.target_sr != out_sr:
            audio_np = _resample(audio_np, self.meta.target_sr, out_sr)
        return audio_np

    # ---------- fallback ----------

    @staticmethod
    def _fallback_pitch_shift(pcm: np.ndarray, sr: int, semitones: int) -> np.ndarray:
        if semitones == 0:
            return pcm.astype(np.float32)
        try:
            import librosa

            return librosa.effects.pitch_shift(
                pcm.astype(np.float32), sr=sr, n_steps=float(semitones)
            ).astype(np.float32)
        except Exception:  # noqa: BLE001
            return pcm.astype(np.float32)


# ---------- 工具函数 ----------

def _resample(pcm: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return pcm.astype(np.float32)
    try:
        import resampy

        return resampy.resample(pcm.astype(np.float32), sr_in, sr_out, filter="kaiser_fast")
    except ImportError:
        try:
            import librosa

            return librosa.resample(pcm.astype(np.float32), orig_sr=sr_in, target_sr=sr_out)
        except ImportError:
            # 最后兜底：线性插值（质量差但能跑）
            ratio = sr_out / sr_in
            n_out = int(round(pcm.shape[0] * ratio))
            x_in = np.linspace(0, 1, pcm.shape[0], endpoint=False)
            x_out = np.linspace(0, 1, n_out, endpoint=False)
            return np.interp(x_out, x_in, pcm).astype(np.float32)


def _align_length(arr: np.ndarray, target_len: int) -> np.ndarray:
    """把任意长度的 1D 数组缩放/裁剪到目标长度。"""
    if arr.shape[0] == target_len:
        return arr
    if arr.shape[0] > target_len:
        return arr[:target_len]
    pad = target_len - arr.shape[0]
    return np.concatenate([arr, np.zeros(pad, dtype=arr.dtype)])


def _append_frames(
    old: Optional[np.ndarray],
    new: np.ndarray,
    max_frames: int,
) -> np.ndarray:
    if old is None or old.size == 0:
        merged = new
    elif new.size == 0:
        merged = old
    else:
        merged = np.concatenate([old, new], axis=0)
    if merged.shape[0] > max_frames:
        merged = merged[-max_frames:]
    return merged.copy()


def _append_audio(old: np.ndarray, new: np.ndarray, max_samples: int) -> np.ndarray:
    merged = new if old.size == 0 else np.concatenate([old, new])
    if merged.shape[0] > max_samples:
        merged = merged[-max_samples:]
    return merged.astype(np.float32, copy=True)


def _estimate_tail_count(
    total_count: int,
    total_samples: int,
    new_samples: int,
) -> int:
    if total_count <= 0:
        return 0
    if total_samples <= 0 or new_samples >= total_samples:
        return total_count
    ratio = max(0.0, min(1.0, new_samples / total_samples))
    return max(1, min(total_count, int(round(total_count * ratio))))


def _apply_rms_mix(
    audio_np: np.ndarray,
    source: np.ndarray,
    source_sr: int,
    out_sr: int,
    rms_mix_rate: float,
) -> np.ndarray:
    src = _resample(source, source_sr, out_sr) if source_sr != out_sr else source.astype(np.float32)
    src = _align_length(src, audio_np.shape[0])
    src_rms = float(np.sqrt(np.mean(np.square(src)) + 1e-8))
    out_rms = float(np.sqrt(np.mean(np.square(audio_np)) + 1e-8))
    if src_rms <= 1e-5 or out_rms <= 1e-5:
        return audio_np
    target_rms = out_rms * (1.0 - rms_mix_rate) + src_rms * rms_mix_rate
    return (audio_np * (target_rms / out_rms)).astype(np.float32)


def _supports_stream_decode(net_g) -> bool:
    try:
        sig = inspect.signature(net_g.infer)
    except (TypeError, ValueError):
        return False
    params = sig.parameters
    if any(p.kind == p.VAR_POSITIONAL for p in params.values()):
        return True
    return {"skip_head", "return_length"}.issubset(params)
