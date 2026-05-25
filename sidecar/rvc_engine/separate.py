"""离线人声分离（Demucs 包装）。

设计：
- 任务异步：start_separation 立即返回 session_id，后台线程跑 Demucs
- 状态：pending / running / done / failed / cancelled
- 输出：vocals.wav + other.wav（two_stems 模式），落到 SidecarConfig.separation_dir/<session_id>/
- 取消：通过 threading.Event 让推理循环主动 break；Demucs 内部用 apply_model
  时不可中断，我们退而求其次：在分离结果落盘前检查 cancel flag
- 模型：默认 htdemucs，可选 htdemucs_ft / htdemucs_6s / mdx_extra 等

注意：Demucs 模型首次使用会自动下载到 torch hub cache，~80MB。
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

from .config import SidecarConfig


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
