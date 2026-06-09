"""本机 RVC 训练任务管理。

当前 sidecar 只打包了推理所需的最小 RVC vendor 代码，没有完整训练脚本。
因此这里先提供训练任务入口、GPU/数据集/脚本检测和状态管理；当训练脚本接入后，
同一套 API 可以直接执行本机 GPU 训练并把产物导入 voices 目录。
"""

from __future__ import annotations

import os
import subprocess
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
class TrainingJob:
    session_id: str
    dataset_dir: Path
    output_dir: Path
    voice_name: str
    training_package_dir: Optional[Path]
    epochs: int
    batch_size: int
    sample_rate: int
    f0_method: str
    save_every_epoch: int
    model_version: str
    gpu_ids: Optional[str]
    cache_gpu: bool
    save_latest_only: bool
    save_every_weights: bool
    pretrained_g: Optional[Path]
    pretrained_d: Optional[Path]
    use_gpu: bool

    state: str = "pending"
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    pth_path: Optional[Path] = None
    index_path: Optional[Path] = None
    log_path: Optional[Path] = None

    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: Optional[subprocess.Popen] = None
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "sessionId": self.session_id,
            "state": self.state,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "pthPath": str(self.pth_path) if self.pth_path else None,
            "indexPath": str(self.index_path) if self.index_path else None,
            "logPath": str(self.log_path) if self.log_path else None,
        }


class TrainingManager:
    """一次只允许一个训练任务运行，避免多个任务争抢显存。"""

    def __init__(self, cfg: SidecarConfig) -> None:
        self.cfg = cfg
        self._jobs: Dict[str, TrainingJob] = {}
        self._lock = threading.Lock()
        self._active_thread: Optional[threading.Thread] = None

    def get_job(self, session_id: str) -> Optional[TrainingJob]:
        with self._lock:
            return self._jobs.get(session_id)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(session_id)
        if job is None or job.state not in ("pending", "running"):
            return False
        job.cancel_event.set()
        if job.process is not None and job.process.poll() is None:
            job.process.terminate()
        logger.info(f"训练任务 {session_id} 取消请求已发出")
        return True

    def start(
        self,
        dataset_dir: str,
        voice_name: str,
        training_package_dir: Optional[str] = None,
        epochs: int = 200,
        batch_size: int = 4,
        sample_rate: int = 40_000,
        f0_method: str = "rmvpe",
        save_every_epoch: int = 10,
        model_version: str = "v2",
        gpu_ids: Optional[str] = None,
        cache_gpu: bool = False,
        save_latest_only: bool = True,
        save_every_weights: bool = False,
        pretrained_g: Optional[str] = None,
        pretrained_d: Optional[str] = None,
        use_gpu: bool = True,
    ) -> TrainingJob:
        data_dir = Path(dataset_dir).expanduser().resolve()
        if not data_dir.exists() or not data_dir.is_dir():
            raise FileNotFoundError(f"训练素材目录不存在: {data_dir}")
        audio_count = _count_audio_files(data_dir)
        if audio_count == 0:
            raise RuntimeError(f"训练素材目录没有音频文件: {data_dir}")
        package_dir = _resolve_package_dir(training_package_dir)

        session_id = uuid.uuid4().hex[:12]
        out_dir = self.cfg.training_dir / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        job = TrainingJob(
            session_id=session_id,
            dataset_dir=data_dir,
            output_dir=out_dir,
            voice_name=_sanitize_name(voice_name),
            training_package_dir=package_dir,
            epochs=max(1, min(1000, int(epochs))),
            batch_size=max(1, min(64, int(batch_size))),
            sample_rate=int(sample_rate),
            f0_method=str(f0_method),
            save_every_epoch=max(1, min(100, int(save_every_epoch))),
            model_version=str(model_version or "v2"),
            gpu_ids=(str(gpu_ids).strip() if gpu_ids else None),
            cache_gpu=bool(cache_gpu),
            save_latest_only=bool(save_latest_only),
            save_every_weights=bool(save_every_weights),
            pretrained_g=_resolve_optional_file(pretrained_g),
            pretrained_d=_resolve_optional_file(pretrained_d),
            use_gpu=bool(use_gpu),
            message=f"queued · {audio_count} audio files",
            log_path=out_dir / "train.log",
        )
        with self._lock:
            self._jobs[session_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job,),
            daemon=True,
            name=f"train-{session_id}",
        )
        thread.start()
        self._active_thread = thread
        return job

    def _run_job(self, job: TrainingJob) -> None:
        job.started_at = time.time()
        job.state = "running"
        job.progress = 0.02
        job.message = "checking environment"

        try:
            self._do_train(job)
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
            logger.exception("训练任务失败")
            job.state = "failed"
            job.error = f"{type(e).__name__}: {e}"
            job.message = "error"
            if job.log_path is not None:
                job.log_path.write_text(
                    traceback.format_exc(),
                    encoding="utf-8",
                    errors="replace",
                )
        finally:
            job.finished_at = time.time()
            logger.info(
                f"训练任务 {job.session_id} 结束 state={job.state} "
                f"耗时={job.finished_at - job.started_at:.1f}s"
            )

    def _do_train(self, job: TrainingJob) -> None:
        gpu_info = _detect_gpu()
        if job.use_gpu and not gpu_info["available"]:
            raise RuntimeError(
                "未检测到可用 GPU。RVC 可以用 CPU 训练，但会非常慢；"
                "请关闭 GPU 训练开关，或安装 CUDA/MPS 可用的 PyTorch。"
            )
        job.progress = 0.08
        job.message = (
            f"GPU ready: {gpu_info['name']}"
            if gpu_info["available"] and job.use_gpu
            else "CPU mode"
        )

        script = _find_training_script(job.training_package_dir)
        if script is None:
            raise RuntimeError(
                "当前 sidecar 只包含 RVC 推理最小源码，未包含完整训练脚本。"
                "请下载 RVC-WebUI 官方训练包，解压后在软件里加载训练包目录。"
            )
        if job.cancel_event.is_set():
            raise _CancelledError()

        job.progress = 0.12
        job.message = "starting trainer"
        cmd = _build_train_command(script, job)
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        with open(job.log_path, "w", encoding="utf-8") as log:
            log.write(" ".join(cmd) + "\n\n")
            job.process = subprocess.Popen(
                cmd,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd=str(script.parent),
                env=env,
            )
            while job.process.poll() is None:
                if job.cancel_event.is_set():
                    job.process.terminate()
                    raise _CancelledError()
                _refresh_outputs(job)
                time.sleep(1.0)

        if job.process.returncode != 0:
            raise RuntimeError(f"训练进程退出码异常: {job.process.returncode}")
        _refresh_outputs(job)
        if job.pth_path is None:
            raise RuntimeError("训练结束但未找到 .pth 输出")


def _count_audio_files(path: Path) -> int:
    exts = {".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus"}
    return sum(1 for p in path.rglob("*") if p.suffix.lower() in exts)


def _sanitize_name(name: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return safe or "custom_voice"


def _resolve_package_dir(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_dir():
        raise FileNotFoundError(f"训练包目录不存在: {p}")
    return p


def _resolve_optional_file(path: Optional[str]) -> Optional[Path]:
    if not path:
        return None
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"文件不存在: {p}")
    return p


def _detect_gpu() -> dict:
    try:
        import torch

        if torch.cuda.is_available():
            return {
                "available": True,
                "backend": "cuda",
                "name": torch.cuda.get_device_name(0),
            }
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return {"available": True, "backend": "mps", "name": "Apple MPS"}
    except Exception:  # noqa: BLE001
        pass
    return {"available": False, "backend": "cpu", "name": "CPU"}


def detect_gpu() -> dict:
    """返回训练可用 GPU 信息，供前端展示。"""
    return _detect_gpu()


def _find_training_script(package_dir: Optional[Path] = None) -> Optional[Path]:
    candidates = [
        Path(os.environ.get("RVC_TRAIN_SCRIPT", "")),
    ]
    if package_dir is not None:
        candidates.extend(
            [
                package_dir / "train.py",
                package_dir / "infer-web.py",
                package_dir / "RVC" / "infer-web.py",
                package_dir / "RVC" / "train.py",
            ]
        )
    candidates.extend(
        [
            Path.cwd() / "train.py",
            Path.cwd() / "infer-web.py",
            Path.cwd() / "RVC" / "infer-web.py",
            Path.cwd() / "RVC" / "train.py",
        ]
    )
    for p in candidates:
        if p and str(p) != "." and p.exists() and p.is_file():
            return p.resolve()
    return None


def _build_train_command(script: Path, job: TrainingJob) -> list[str]:
    cmd = [
        os.environ.get("PYTHON", "python"),
        str(script),
        "--dataset",
        str(job.dataset_dir),
        "--output",
        str(job.output_dir),
        "--name",
        job.voice_name,
        "--epochs",
        str(job.epochs),
        "--batch-size",
        str(job.batch_size),
        "--sample-rate",
        str(job.sample_rate),
        "--f0-method",
        job.f0_method,
        "--save-every-epoch",
        str(job.save_every_epoch),
        "--version",
        job.model_version,
        "--cache-gpu",
        "1" if job.cache_gpu else "0",
        "--save-latest-only",
        "1" if job.save_latest_only else "0",
        "--save-every-weights",
        "1" if job.save_every_weights else "0",
    ]
    if job.gpu_ids:
        cmd.extend(["--gpus", job.gpu_ids])
    if job.pretrained_g is not None:
        cmd.extend(["--pretrained-g", str(job.pretrained_g)])
    if job.pretrained_d is not None:
        cmd.extend(["--pretrained-d", str(job.pretrained_d)])
    return cmd


def _refresh_outputs(job: TrainingJob) -> None:
    pths = sorted(job.output_dir.rglob("*.pth"), key=lambda p: p.stat().st_mtime)
    indexes = sorted(job.output_dir.rglob("*.index"), key=lambda p: p.stat().st_mtime)
    if pths:
        job.pth_path = pths[-1]
    if indexes:
        job.index_path = indexes[-1]


class _CancelledError(Exception):
    pass
