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
    ) -> np.ndarray:
        """对一段已经包含足够上下文的 PCM 做 RVC 推理。

        约定：调用方（pipeline.py）已经把上下文拼接好；本方法不维护跨调用状态。
        """
        if not self._loaded or self.meta is None or self._net_g is None:
            return self._fallback_pitch_shift(pcm, in_sr, pitch_semitones)

        import torch

        # 1) 重采样到 16kHz 给 ContentVec / RMVPE 用
        pcm_16k = _resample(pcm, in_sr, 16_000) if in_sr != 16_000 else pcm
        pcm_16k = pcm_16k.astype(np.float32)

        # 2) ContentVec 特征
        assert self._content_vec is not None
        feats = self._content_vec.extract(pcm_16k)  # [T, D] numpy
        feats_t = torch.from_numpy(feats).to(self.device)
        feats_t = feats_t.half() if self.is_half else feats_t.float()
        feats_t = feats_t.unsqueeze(0)  # [1, T, D]

        # 3) Faiss 检索增强（可选）
        if self._faiss_index is not None and self._big_npy is not None and index_rate > 0:
            feats_np = feats.astype(np.float32)
            try:
                _, ix = self._faiss_index.search(feats_np, k=8)
                # 距离权重
                weights = np.square(1 / (np.linalg.norm(
                    self._big_npy[ix] - feats_np[:, None],
                    axis=-1,
                ) + 1e-8))
                weights /= weights.sum(axis=-1, keepdims=True)
                searched = (
                    self._big_npy[ix] * np.expand_dims(weights, axis=-1)
                ).sum(axis=-2)
                searched_t = torch.from_numpy(searched).to(self.device)
                searched_t = searched_t.half() if self.is_half else searched_t.float()
                searched_t = searched_t.unsqueeze(0)
                feats_t = (1 - index_rate) * feats_t + index_rate * searched_t
            except Exception as e:  # noqa: BLE001
                logger.debug(f"Faiss 检索失败，跳过: {e}")

        # 4) 上采样特征到 RVC 期望的帧率（双倍插值）
        feats_t = torch.nn.functional.interpolate(
            feats_t.permute(0, 2, 1), scale_factor=2
        ).permute(0, 2, 1)
        t_feats = feats_t.shape[1]

        # 5) F0 提取
        if self.meta.if_f0:
            assert self._f0 is not None
            f0_coarse_np, f0_cont_np = self._f0.extract(
                pcm_16k, pitch_semitones=pitch_semitones
            )
            # 帧数对齐
            f0_coarse_np = _align_length(f0_coarse_np, t_feats)
            f0_cont_np = _align_length(f0_cont_np, t_feats)
            pitch_t = torch.from_numpy(f0_coarse_np).to(self.device).long().unsqueeze(0)
            pitchf_t = torch.from_numpy(f0_cont_np).to(self.device)
            pitchf_t = pitchf_t.half() if self.is_half else pitchf_t.float()
            pitchf_t = pitchf_t.unsqueeze(0)
        else:
            pitch_t = pitchf_t = None

        # 6) RVC 推理
        sid_t = torch.tensor([0], device=self.device).long()
        feats_len_t = torch.tensor([t_feats], device=self.device).long()

        with torch.no_grad():
            if self.meta.if_f0:
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
                    sid_t,
                )[0][0, 0]
        audio_np = audio.float().cpu().numpy().astype(np.float32)

        # 7) 输出端重采样
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
