"""FastAPI + WebSocket 入口。

协议（与 Rust 端 `ipc/ws_client.rs` 严格对齐）：

客户端 -> 服务端：
- {"type":"init","voice_id":"yujie","pitch":0,"in_sr":48000,"out_sr":48000}  # text
- <PCM f32 LE bytes>                                                          # binary
- {"type":"set_voice","voice_id":"loli"}                                      # text
- {"type":"set_pitch","pitch":4}                                              # text

服务端 -> 客户端：
- {"type":"ready"}
- <PCM f32 LE bytes>
- {"type":"error","message":"..."}
- {"type":"status","state":"running"}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from .config import SidecarConfig
from .pipeline import RVCPipeline
from .separate import SeparationManager
from .shm_transport import ShmTransport
from .train import TrainingManager, detect_gpu


class SeparateRequest(BaseModel):
    input_path: str
    model: str = "htdemucs"
    two_stems: bool = True


class RealtimeConfigRequest(BaseModel):
    responseThreshold: float = 0.5
    voiceThickness: float = 0.0
    indexRate: float = 0.5
    rmsMixRate: float = 0.25
    protect: float = 0.33
    loudness: float = 1.0
    f0Method: str = "rmvpe"
    f0FilterRadius: int = 3
    resampleSr: int = 0
    sampleRateMode: str = "device"
    customSampleRate: int = 48_000
    chunkSize: int = 4096
    harvestProcesses: int = 2
    crossfadeMs: int = 10
    extraInferenceMs: int = 2500
    bufferMs: int = 500


class TrainRequest(BaseModel):
    dataset_dir: str
    voice_name: str
    training_package_dir: Optional[str] = None
    epochs: int = 200
    batch_size: int = 4
    sample_rate: int = 40_000
    f0_method: str = "rmvpe"
    save_every_epoch: int = 10
    model_version: str = "v2"
    gpu_ids: Optional[str] = None
    cache_gpu: bool = False
    save_latest_only: bool = True
    save_every_weights: bool = False
    pretrained_g: Optional[str] = None
    pretrained_d: Optional[str] = None
    use_gpu: bool = True


def create_app(cfg: SidecarConfig) -> FastAPI:
    app = FastAPI(title="rvc-engine")
    pipeline = RVCPipeline(cfg)
    separation = SeparationManager(cfg)
    training = TrainingManager(cfg)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "device": pipeline.device,
                "loaded_voice": pipeline.current_voice_id,
                "version": "0.1.0",
            }
        )

    @app.get("/voices")
    async def voices() -> JSONResponse:
        return JSONResponse({"voices": pipeline.list_voices()})

    @app.get("/profile")
    async def profile() -> JSONResponse:
        return JSONResponse({"profile": pipeline.profile()})

    # ---------- 离线人声分离 ----------

    @app.post("/separate")
    async def start_separate(req: SeparateRequest) -> JSONResponse:
        try:
            job = await asyncio.to_thread(
                separation.start, req.input_path, req.model, req.two_stems
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("启动分离任务失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"session_id": job.session_id})

    @app.get("/separate/status/{session_id}")
    async def separate_status(session_id: str) -> JSONResponse:
        job = separation.get_job(session_id)
        if job is None:
            raise HTTPException(status_code=404, detail="session not found")
        return JSONResponse(job.to_dict())

    @app.post("/separate/cancel/{session_id}")
    async def separate_cancel(session_id: str) -> JSONResponse:
        ok = separation.cancel(session_id)
        return JSONResponse({"cancelled": ok})

    # ---------- 本机模型训练 ----------

    @app.get("/train/gpu")
    async def train_gpu() -> JSONResponse:
        return JSONResponse(await asyncio.to_thread(detect_gpu))

    @app.post("/train")
    async def start_train(req: TrainRequest) -> JSONResponse:
        try:
            job = await asyncio.to_thread(
                training.start,
                dataset_dir=req.dataset_dir,
                voice_name=req.voice_name,
                training_package_dir=req.training_package_dir,
                epochs=req.epochs,
                batch_size=req.batch_size,
                sample_rate=req.sample_rate,
                f0_method=req.f0_method,
                save_every_epoch=req.save_every_epoch,
                model_version=req.model_version,
                gpu_ids=req.gpu_ids,
                cache_gpu=req.cache_gpu,
                save_latest_only=req.save_latest_only,
                save_every_weights=req.save_every_weights,
                pretrained_g=req.pretrained_g,
                pretrained_d=req.pretrained_d,
                use_gpu=req.use_gpu,
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:  # noqa: BLE001
            logger.exception("启动训练任务失败")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return JSONResponse({"session_id": job.session_id})

    @app.get("/train/status/{session_id}")
    async def train_status(session_id: str) -> JSONResponse:
        job = training.get_job(session_id)
        if job is None:
            raise HTTPException(status_code=404, detail="session not found")
        return JSONResponse(job.to_dict())

    @app.post("/train/cancel/{session_id}")
    async def train_cancel(session_id: str) -> JSONResponse:
        ok = training.cancel(session_id)
        return JSONResponse({"cancelled": ok})

    @app.websocket("/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        logger.info("WebSocket 连接建立")

        in_sr: Optional[int] = None
        out_sr: Optional[int] = None
        ready_sent = False
        last_profile_sent = 0.0
        shm: Optional[ShmTransport] = None

        try:
            while True:
                msg = await ws.receive()
                # text 控制消息
                if "text" in msg and msg["text"] is not None:
                    payload = json.loads(msg["text"])
                    mtype = payload.get("type")

                    if mtype == "init":
                        in_sr = int(payload["in_sr"])
                        out_sr = int(payload["out_sr"])
                        voice_id = payload["voice_id"]
                        pitch = int(payload.get("pitch", 0))
                        config = RealtimeConfigRequest.model_validate(
                            payload.get("config", {})
                        )
                        shm_cfg = payload.get("shm")
                        if shm_cfg:
                            try:
                                shm = ShmTransport(
                                    input_path=str(shm_cfg["inputPath"]),
                                    output_path=str(shm_cfg["outputPath"]),
                                    capacity_samples=int(shm_cfg["capacitySamples"]),
                                )
                                logger.info("shared-memory PCM transport enabled")
                            except Exception as e:  # noqa: BLE001
                                logger.warning(f"shared-memory transport disabled: {e}")
                                shm = None
                        await asyncio.to_thread(
                            pipeline.prepare,
                            voice_id,
                            pitch,
                            in_sr,
                            out_sr,
                            config.model_dump(),
                        )
                        await ws.send_text(
                            json.dumps({"type": "ready", "use_shm": shm is not None})
                        )
                        ready_sent = True
                        logger.info(
                            f"init voice={voice_id} pitch={pitch} in_sr={in_sr} out_sr={out_sr}"
                        )

                    elif mtype == "set_voice":
                        await asyncio.to_thread(pipeline.set_voice, payload["voice_id"])
                        await ws.send_text(
                            json.dumps({"type": "status", "state": "voice_changed"})
                        )

                    elif mtype == "set_pitch":
                        pipeline.set_pitch(int(payload["pitch"]))
                        await ws.send_text(
                            json.dumps({"type": "status", "state": "pitch_changed"})
                        )

                    elif mtype == "set_realtime_config":
                        config = RealtimeConfigRequest.model_validate(
                            payload.get("config", {})
                        )
                        await asyncio.to_thread(
                            pipeline.set_realtime_config,
                            config.model_dump(),
                        )
                        await ws.send_text(
                            json.dumps({"type": "status", "state": "config_changed"})
                        )

                    elif mtype == "shm_audio":
                        if not ready_sent or shm is None:
                            continue
                        samples = shm.input.read()
                        if samples.size == 0:
                            continue
                        out = await asyncio.to_thread(pipeline.process, samples)
                        if out is not None and out.size > 0:
                            shm.output.write_lossy(out)
                        now = time.monotonic()
                        if now - last_profile_sent >= 0.5:
                            await _send_profile(ws, pipeline)
                            last_profile_sent = now

                    else:
                        logger.warning(f"未知文本消息: {payload}")

                # binary 音频数据
                elif "bytes" in msg and msg["bytes"] is not None:
                    if not ready_sent:
                        # 还没 init，丢弃
                        continue
                    raw: bytes = msg["bytes"]
                    if len(raw) % 4 != 0:
                        await ws.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "message": "binary length not multiple of 4",
                                }
                            )
                        )
                        continue
                    samples = np.frombuffer(raw, dtype=np.float32)
                    out = await asyncio.to_thread(pipeline.process, samples)
                    if out is not None and out.size > 0:
                        await ws.send_bytes(out.astype(np.float32).tobytes())
                    now = time.monotonic()
                    if now - last_profile_sent >= 0.5:
                        await _send_profile(ws, pipeline)
                        last_profile_sent = now

        except WebSocketDisconnect:
            logger.info("WebSocket 断开")
        except Exception as e:  # noqa: BLE001
            logger.exception("WebSocket 处理异常")
            try:
                await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            except Exception:  # noqa: BLE001
                pass
        finally:
            if shm is not None:
                shm.close()

    return app


async def _send_profile(ws: WebSocket, pipeline: RVCPipeline) -> None:
    profile = pipeline.profile()
    if profile:
        await ws.send_text(json.dumps({"type": "profile", "profile": profile}))


def main() -> None:
    parser = argparse.ArgumentParser(description="RVC sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-gpu", action="store_true", help="强制 CPU 推理")
    args = parser.parse_args()

    cfg = SidecarConfig(host=args.host, port=args.port, use_gpu=not args.no_gpu)
    logger.info(f"启动 sidecar host={cfg.host} port={cfg.port} use_gpu={cfg.use_gpu}")

    import uvicorn

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", ws_max_size=64 * 1024 * 1024)


if __name__ == "__main__":
    main()
