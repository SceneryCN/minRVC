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
import struct
from typing import Optional

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from loguru import logger
from pydantic import BaseModel

from .config import SidecarConfig
from .pipeline import RVCPipeline
from .separate import SeparationManager


class SeparateRequest(BaseModel):
    input_path: str
    model: str = "htdemucs"
    two_stems: bool = True


def create_app(cfg: SidecarConfig) -> FastAPI:
    app = FastAPI(title="rvc-engine")
    pipeline = RVCPipeline(cfg)
    separation = SeparationManager(cfg)

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

    @app.websocket("/stream")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        logger.info("WebSocket 连接建立")

        in_sr: Optional[int] = None
        out_sr: Optional[int] = None
        ready_sent = False

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
                        await asyncio.to_thread(
                            pipeline.prepare, voice_id, pitch, in_sr, out_sr
                        )
                        await ws.send_text(json.dumps({"type": "ready"}))
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
                    samples = np.frombuffer(raw, dtype=np.float32).copy()
                    out = await asyncio.to_thread(pipeline.process, samples)
                    if out is not None and out.size > 0:
                        await ws.send_bytes(out.astype(np.float32).tobytes())

        except WebSocketDisconnect:
            logger.info("WebSocket 断开")
        except Exception as e:  # noqa: BLE001
            logger.exception("WebSocket 处理异常")
            try:
                await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
            except Exception:  # noqa: BLE001
                pass

    return app


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
