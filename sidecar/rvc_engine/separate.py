"""离线人声分离。

设计：
- 任务异步：start_separation 立即返回 session_id，后台线程跑分离模型
- 状态：pending / running / done / failed / cancelled
- 输出：vocals.wav + other.wav（two_stems 模式），落到 SidecarConfig.separation_dir/<session_id>/
- 取消：通过 threading.Event 让推理前后主动 break；模型内部推理通常不可中断
- 模型：Demucs 内置模型 + audio-separator / UVR 系 RoFormer、MDX23C

注意：模型首次使用会自动下载到本机缓存。RoFormer / MDX23C 模型较大，不打进安装包。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from .config import SidecarConfig


DEMUCS_MODELS = {"htdemucs", "htdemucs_ft", "htdemucs_6s", "mdx_extra"}
AUDIO_SEPARATOR_MODELS = {
    # UVR / audio-separator 模型文件名。保持真实文件名，便于用户按错误提示排查缓存。
    "roformer_mel_band": "vocals_mel_band_roformer.ckpt",
    "bs_roformer": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
    "mdx23c": "MDX23C-8KFFT-InstVoc_HQ.ckpt",
}


@dataclass
class SeparationJob:
    session_id: str
    input_path: Path
    output_dir: Path
    model: str
    two_stems: bool

    state: str = "pending"  # pending / running / done / failed / cancelled
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    vocals_path: Optional[Path] = None
    other_path: Optional[Path] = None

    cancel_event: threading.Event = field(default_factory=threading.Event)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "vocalsPath": str(self.vocals_path) if self.vocals_path else None,
            "otherPath": str(self.other_path) if self.other_path else None,
        }


class SeparationManager:
    """全局分离任务管理器。一次只允许一个任务在跑（避免显存爆）。"""

    def __init__(self, cfg: SidecarConfig) -> None:
        self.cfg = cfg
        self._jobs: Dict[str, SeparationJob] = {}
        self._lock = threading.Lock()
        self._active_thread: Optional[threading.Thread] = None

    def list_jobs(self) -> Dict[str, SeparationJob]:
        with self._lock:
            return dict(self._jobs)

    def get_job(self, session_id: str) -> Optional[SeparationJob]:
        with self._lock:
            return self._jobs.get(session_id)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(session_id)
        if job and job.state in ("pending", "running"):
            job.cancel_event.set()
            logger.info(f"分离任务 {session_id} 取消请求已发出")
            return True
        return False

    def start(
        self,
        input_path: str,
        model: str = "htdemucs",
        two_stems: bool = True,
    ) -> SeparationJob:
        in_path = Path(input_path).expanduser().resolve()
        if not in_path.exists():
            raise FileNotFoundError(f"输入文件不存在: {in_path}")

        session_id = uuid.uuid4().hex[:12]
        out_dir = self.cfg.separation_dir / session_id
        out_dir.mkdir(parents=True, exist_ok=True)

        job = SeparationJob(
            session_id=session_id,
            input_path=in_path,
            output_dir=out_dir,
            model=model,
            two_stems=two_stems,
        )
        with self._lock:
            self._jobs[session_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job,),
            daemon=True,
            name=f"separate-{session_id}",
        )
        thread.start()
        self._active_thread = thread
        return job

    def _run_job(self, job: SeparationJob) -> None:
        job.started_at = time.time()
        job.state = "running"
        job.message = "loading model"

        try:
            self._do_separation(job)
            if job.cancel_event.is_set():
                job.state = "cancelled"
                job.message = "user cancelled"
            else:
                job.state = "done"
                job.progress = 1.0
                job.message = "completed"
        except _CancelledError:
            job.state = "cancelled"
            job.message = "user cancelled"
        except Exception as e:  # noqa: BLE001
            logger.exception("分离任务失败")
            job.state = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.message = "error"
        finally:
            job.finished_at = time.time()
            logger.info(
                f"分离任务 {job.session_id} 结束 state={job.state} "
                f"耗时={job.finished_at - job.started_at:.1f}s"
            )

    def _do_separation(self, job: SeparationJob) -> None:
        if job.model in DEMUCS_MODELS:
            self._do_demucs(job)
            return
        if _audio_separator_model_filename(job.model) is not None:
            self._do_audio_separator(job)
            return
        raise ValueError(f"未知分离模型: {job.model}")

    def _do_demucs(self, job: SeparationJob) -> None:
        # 延迟导入：Demucs 启动开销较大
        try:
            import torch
            import torchaudio
            from demucs.apply import apply_model
            from demucs.audio import save_audio
            from demucs.pretrained import get_model
        except ImportError as e:
            raise RuntimeError(
                f"Demucs 未安装：{e}\n请运行 pip install demucs 或参考 sidecar/requirements.txt"
            ) from e

        device = _select_device()
        logger.info(f"分离 {job.session_id}: 模型={job.model} device={device}")
        job.message = f"loading {job.model}"
        if job.cancel_event.is_set():
            raise _CancelledError()

        model = get_model(job.model)
        model.to(device)
        model.eval()
        job.progress = 0.1

        if job.cancel_event.is_set():
            raise _CancelledError()

        # 读取并重采样
        job.message = "loading audio"
        wav, sr = torchaudio.load(str(job.input_path))
        # Demucs 模型固定 44.1kHz 立体声
        target_sr = model.samplerate
        target_ch = model.audio_channels
        if sr != target_sr:
            wav = torchaudio.functional.resample(wav, sr, target_sr)
        if wav.shape[0] == 1 and target_ch == 2:
            wav = wav.repeat(2, 1)
        elif wav.shape[0] > target_ch:
            wav = wav[:target_ch]
        job.progress = 0.2

        if job.cancel_event.is_set():
            raise _CancelledError()

        # Demucs apply_model 的输入是 [batch, channels, samples]
        ref = wav.mean(0)  # 用于响度归一化
        wav_norm = (wav - ref.mean()) / max(wav.std().item(), 1e-8)
        wav_in = wav_norm.unsqueeze(0).to(device)

        job.message = "separating"
        with torch.no_grad():
            sources = apply_model(
                model,
                wav_in,
                shifts=1,
                split=True,
                overlap=0.25,
                progress=False,
            )[0]
        sources = sources * wav.std().item() + ref.mean()
        # sources: [stems, channels, samples]
        job.progress = 0.85

        if job.cancel_event.is_set():
            raise _CancelledError()

        stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
        logger.info(f"模型 stems: {stem_names}")

        if job.two_stems:
            # 合并 vocals 与非 vocals
            if "vocals" not in stem_names:
                raise RuntimeError(f"模型 {job.model} 不输出 vocals stem")
            v_idx = stem_names.index("vocals")
            vocals = sources[v_idx]
            other = sources.sum(0) - vocals  # 其它 stem 之和

            vocals_path = job.output_dir / "vocals.wav"
            other_path = job.output_dir / "accompaniment.wav"
            save_audio(vocals.cpu(), str(vocals_path), target_sr)
            save_audio(other.cpu(), str(other_path), target_sr)
            job.vocals_path = vocals_path
            job.other_path = other_path
        else:
            # 全部 stem 都落盘；vocals_path 仍指向 vocals 方便前端
            for i, name in enumerate(stem_names):
                save_audio(
                    sources[i].cpu(),
                    str(job.output_dir / f"{name}.wav"),
                    target_sr,
                )
            if "vocals" in stem_names:
                job.vocals_path = job.output_dir / "vocals.wav"

        job.progress = 1.0

    def _do_audio_separator(self, job: SeparationJob) -> None:
        model_filename = _audio_separator_model_filename(job.model)
        if model_filename is None:
            raise ValueError(f"未知 audio-separator 模型: {job.model}")

        try:
            from audio_separator.separator import Separator
        except ImportError as e:
            raise RuntimeError(
                "RoFormer / MDX23C 需要安装可选依赖 audio-separator。"
                "请在 sidecar 环境运行：pip install audio-separator"
            ) from e

        device = _select_device()
        use_cuda = device == "cuda"
        logger.info(
            f"分离 {job.session_id}: audio-separator 模型={model_filename} device={device}"
        )
        job.message = f"loading {model_filename}"
        if job.cancel_event.is_set():
            raise _CancelledError()

        # audio-separator 内部使用 ONNX Runtime / PyTorch / librosa 等后端。
        # output_format 固定 wav，便于前端和训练链路消费。
        separator_kwargs = {
            "log_level": "INFO",
            "model_file_dir": str(self.cfg.audio_separator_models_dir),
            "output_dir": str(job.output_dir),
            "output_format": "WAV",
            "use_cuda": use_cuda,
        }
        separator = _new_separator(Separator, separator_kwargs)
        separator.load_model(model_filename=model_filename)
        job.progress = 0.2

        if job.cancel_event.is_set():
            raise _CancelledError()

        job.message = "separating"
        outputs = separator.separate(str(job.input_path))
        job.progress = 0.85

        if job.cancel_event.is_set():
            raise _CancelledError()

        output_paths = _resolve_audio_separator_outputs(job.output_dir, outputs)
        vocals_path, other_path = _pick_vocal_outputs(output_paths)
        if vocals_path is None:
            raise RuntimeError(
                f"模型 {model_filename} 未产出可识别的人声文件，输出: "
                f"{[p.name for p in output_paths]}"
            )
        job.vocals_path = _copy_or_rename(vocals_path, job.output_dir / "vocals.wav")
        if other_path is not None:
            job.other_path = _copy_or_rename(
                other_path,
                job.output_dir / "accompaniment.wav",
            )
        job.progress = 1.0


class _CancelledError(Exception):
    pass


def _select_device() -> str:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def _new_separator(separator_cls, kwargs: dict):
    """按已安装 audio-separator 版本支持的参数初始化。"""
    try:
        import inspect

        sig = inspect.signature(separator_cls)
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            return separator_cls(**kwargs)
        supported = {k: v for k, v in kwargs.items() if k in sig.parameters}
        return separator_cls(**supported)
    except (TypeError, ValueError):
        fallback = {
            "model_file_dir": kwargs["model_file_dir"],
            "output_dir": kwargs["output_dir"],
        }
        return separator_cls(**fallback)


def _audio_separator_model_filename(model: str) -> Optional[str]:
    if model in AUDIO_SEPARATOR_MODELS:
        return AUDIO_SEPARATOR_MODELS[model]
    if model.startswith("audio-separator:"):
        raw = model.split(":", 1)[1].strip()
        return raw or None
    lowered = model.lower()
    if lowered.endswith((".ckpt", ".onnx", ".pth", ".pth.tar")):
        return model
    return None


def _resolve_audio_separator_outputs(output_dir: Path, outputs: object) -> list[Path]:
    paths: list[Path] = []
    if isinstance(outputs, (list, tuple)):
        for item in outputs:
            if isinstance(item, str) and item:
                p = Path(item)
                paths.append(p if p.is_absolute() else output_dir / p)
    elif isinstance(outputs, str) and outputs:
        p = Path(outputs)
        paths.append(p if p.is_absolute() else output_dir / p)

    existing = [p for p in paths if p.exists()]
    if existing:
        return existing
    return sorted(
        [
            p
            for p in output_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".wav", ".flac", ".mp3", ".ogg"}
        ]
    )


def _pick_vocal_outputs(paths: list[Path]) -> tuple[Optional[Path], Optional[Path]]:
    vocals: Optional[Path] = None
    other: Optional[Path] = None
    for p in paths:
        name = p.name.lower()
        if vocals is None and any(k in name for k in ("vocals", "vocal", "voice", "sing")):
            vocals = p
            continue
        if other is None and any(
            k in name
            for k in (
                "instrumental",
                "inst",
                "accompaniment",
                "no_vocals",
                "novocals",
                "karaoke",
                "music",
            )
        ):
            other = p
    if vocals is None and paths:
        vocals = paths[0]
    if other is None and len(paths) > 1:
        other = next((p for p in paths if p != vocals), None)
    return vocals, other


def _copy_or_rename(src: Path, dst: Path) -> Path:
    if src.resolve() == dst.resolve():
        return dst
    if dst.exists():
        dst.unlink()
    try:
        src.replace(dst)
    except OSError:
        import shutil

        shutil.copy2(src, dst)
    return dst
