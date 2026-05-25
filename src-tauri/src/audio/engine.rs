//! 音频引擎：编排 capture / sidecar IPC / output。
//!
//! 数据流：
//!   mic -> capture_stream -> mic_ring(producer)
//!                            ↘
//!                             tokio task: 从 mic_ring 取 chunk → WS 发送
//!                             ↙
//!                             tokio task: WS 接收 chunk → out_ring(producer)
//!                            ↗
//!   out_ring(consumer) → output_stream → VB-Cable
//!
//! 设计为「冷启动」：start() 时一次性建好所有线程/任务；stop() 时全部 drop。

use crate::audio::capture::{build_capture_stream, CaptureStream};
use crate::audio::dsp::{DspProcessor, SharedDspState};
use crate::audio::output::{build_output_stream, OutputStream};
use crate::audio::ring::AudioRingBuffer;
use crate::error::{AppError, AppResult};
use crate::ipc::ws_client::{SidecarClient, SidecarFrame};
use parking_lot::Mutex;
use std::sync::Arc;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum EngineStatus {
    Stopped,
    Starting,
    Running,
    Stopping,
    Error,
}

#[derive(Debug, Clone)]
pub struct StartConfig {
    pub input_device: Option<String>,
    pub output_device: Option<String>,
    pub voice_id: String,
    pub pitch_shift: i32,
    pub sidecar_ws_url: String,
    /// 每次发送给 sidecar 的样本数（@输入采样率，单声道）
    pub chunk_size: usize,
    /// 缓冲允许的最大延迟（秒），用于决定 ringbuf 容量
    pub latency_secs: f32,
}

impl Default for StartConfig {
    fn default() -> Self {
        Self {
            input_device: None,
            output_device: None,
            voice_id: "yujie".into(),
            pitch_shift: 0,
            sidecar_ws_url: "ws://127.0.0.1:8765/stream".into(),
            chunk_size: 1024,
            latency_secs: 0.5,
        }
    }
}

pub struct AudioEngine {
    status: EngineStatus,
    capture: Option<CaptureStream>,
    output: Option<OutputStream>,
    tasks: Vec<JoinHandle<()>>,
    capture_level: Arc<Mutex<f32>>,
    output_level: Arc<Mutex<f32>>,
    stop_tx: Option<mpsc::Sender<()>>,
}

impl Default for AudioEngine {
    fn default() -> Self {
        Self::new()
    }
}

impl AudioEngine {
    pub fn new() -> Self {
        Self {
            status: EngineStatus::Stopped,
            capture: None,
            output: None,
            tasks: Vec::new(),
            capture_level: Arc::new(Mutex::new(0.0)),
            output_level: Arc::new(Mutex::new(0.0)),
            stop_tx: None,
        }
    }

    pub fn status(&self) -> EngineStatus {
        self.status
    }

    pub fn capture_level(&self) -> f32 {
        *self.capture_level.lock()
    }

    pub fn output_level(&self) -> f32 {
        *self.output_level.lock()
    }

    pub async fn start(&mut self, cfg: StartConfig, dsp: SharedDspState) -> AppResult<()> {
        if matches!(self.status, EngineStatus::Running | EngineStatus::Starting) {
            return Ok(());
        }
        self.status = EngineStatus::Starting;
        tracing::info!("启动音频引擎: voice={} pitch={}", cfg.voice_id, cfg.pitch_shift);

        // 1) 先建采集流，确认采样率
        let mic_ring = AudioRingBuffer::new(48_000, 1, cfg.latency_secs);
        let (mic_prod, mut mic_cons) = mic_ring.split();

        let cap = build_capture_stream(cfg.input_device.as_deref(), mic_prod)?;
        self.capture_level = cap.level_meter.clone();

        // 2) 建输出流
        let out_ring = AudioRingBuffer::new(48_000, 1, cfg.latency_secs);
        let (mut out_prod, out_cons) = out_ring.split();

        let out_stream = build_output_stream(cfg.output_device.as_deref(), out_cons)?;

        // 3) 连接 sidecar WebSocket
        let mut client = SidecarClient::connect(&cfg.sidecar_ws_url).await?;
        client
            .send_init(&cfg.voice_id, cfg.pitch_shift, cap.sample_rate, out_stream.sample_rate)
            .await?;

        // 4) 启动两个 tokio 任务：
        //    a) 从 mic_ring 弹 chunk → 经 DSP（降噪 + VAD）→ 发 sidecar；
        //       如果 VAD 判定为静音，跳过发送（节省 GPU / 带宽）。
        //    b) 把 sidecar 返回的数据写入 out_ring。
        let (stop_tx, mut stop_rx) = mpsc::channel::<()>(1);
        let chunk = cfg.chunk_size;
        let (mut to_sidecar, mut from_sidecar) = client.split();

        let capture_sr = cap.sample_rate;
        let dsp_for_task = dsp.clone();
        let send_task = tokio::spawn(async move {
            let mut buf = vec![0.0_f32; chunk];
            let mut dsp_out: Vec<f32> = Vec::with_capacity(chunk * 2);
            let mut processor = DspProcessor::new(capture_sr, dsp_for_task);
            loop {
                tokio::select! {
                    _ = stop_rx.recv() => break,
                    _ = tokio::time::sleep(std::time::Duration::from_millis(5)) => {
                        let mut filled = 0;
                        while filled < chunk {
                            match ringbuf::traits::Consumer::try_pop(&mut mic_cons) {
                                Some(v) => { buf[filled] = v; filled += 1; }
                                None => break,
                            }
                        }
                        if filled == 0 {
                            continue;
                        }
                        // DSP 处理
                        dsp_out.clear();
                        let speaking = processor.process(&buf[..filled], &mut dsp_out);
                        if !speaking || dsp_out.is_empty() {
                            // 静音段：直接丢弃，不送 sidecar
                            continue;
                        }
                        if let Err(e) = to_sidecar.send_audio(&dsp_out).await {
                            tracing::warn!("发送到 sidecar 失败: {e}");
                            break;
                        }
                    }
                }
            }
        });

        let output_level = self.output_level.clone();
        let recv_task = tokio::spawn(async move {
            while let Some(frame) = from_sidecar.next_frame().await {
                match frame {
                    Ok(SidecarFrame::Audio(samples)) => {
                        let mut peak = 0.0_f32;
                        for s in &samples {
                            if s.abs() > peak { peak = s.abs(); }
                            let _ = ringbuf::traits::Producer::try_push(&mut out_prod, *s);
                        }
                        let mut g = output_level.lock();
                        *g = 0.8 * *g + 0.2 * peak;
                    }
                    Ok(SidecarFrame::Status(_)) | Ok(SidecarFrame::Error(_)) => {}
                    Err(e) => {
                        tracing::warn!("sidecar 帧解析错误: {e}");
                        break;
                    }
                }
            }
        });

        self.capture = Some(cap);
        self.output = Some(out_stream);
        self.tasks = vec![send_task, recv_task];
        self.stop_tx = Some(stop_tx);
        self.status = EngineStatus::Running;
        Ok(())
    }

    pub async fn stop(&mut self) -> AppResult<()> {
        if matches!(self.status, EngineStatus::Stopped | EngineStatus::Stopping) {
            return Ok(());
        }
        self.status = EngineStatus::Stopping;
        tracing::info!("停止音频引擎");

        if let Some(tx) = self.stop_tx.take() {
            let _ = tx.send(()).await;
        }
        for t in self.tasks.drain(..) {
            t.abort();
        }
        self.capture = None;
        self.output = None;
        self.status = EngineStatus::Stopped;
        Ok(())
    }
}

impl Drop for AudioEngine {
    fn drop(&mut self) {
        for t in self.tasks.drain(..) {
            t.abort();
        }
    }
}

#[allow(dead_code)]
fn touch_app_error_unused() {
    let _ = AppError::Internal("noop".into());
}
