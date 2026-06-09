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
use crate::ipc::shm_ring::ShmRing;
use crate::ipc::ws_client::{SidecarClient, SidecarFrame};
use crate::ipc::ws_client::ShmInitConfig;
use parking_lot::Mutex;
use parking_lot::RwLock;
use std::collections::VecDeque;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use tokio::task::JoinHandle;

const SIDECAR_READY_TIMEOUT: Duration = Duration::from_secs(90);
const VAD_PREROLL_MS: usize = 200;
const DEFAULT_RING_SAMPLE_RATE: u32 = 96_000;
const SHM_RING_SECS: usize = 8;

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum EngineStatus {
    Stopped,
    Starting,
    Running,
    Stopping,
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
    pub realtime_config: RealtimeConfig,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RealtimeConfig {
    pub response_threshold: f32,
    pub voice_thickness: f32,
    pub index_rate: f32,
    pub rms_mix_rate: f32,
    pub protect: f32,
    pub loudness: f32,
    pub f0_method: String,
    pub f0_filter_radius: u32,
    pub resample_sr: u32,
    pub sample_rate_mode: String,
    pub custom_sample_rate: u32,
    pub chunk_size: usize,
    pub harvest_processes: usize,
    pub crossfade_ms: u32,
    pub extra_inference_ms: u32,
    pub buffer_ms: u32,
}

#[derive(Debug, Clone, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RealtimeProfile {
    pub input_resample_ms: Option<f32>,
    pub contentvec_ms: Option<f32>,
    pub faiss_ms: Option<f32>,
    pub f0_ms: Option<f32>,
    pub generator_ms: Option<f32>,
    pub rms_ms: Option<f32>,
    pub vad_ms: Option<f32>,
    pub pipeline_infer_ms: Option<f32>,
    pub post_ms: Option<f32>,
    pub sola_ms: Option<f32>,
    pub total_ms: Option<f32>,
    pub mode: Option<String>,
    pub device: Option<String>,
    pub f0_method: Option<String>,
    pub chunk_samples: Option<u32>,
    pub rust_dsp_ms: Option<f32>,
    pub rust_send_ms: Option<f32>,
    pub rust_output_ms: Option<f32>,
    pub transport: Option<String>,
}

impl Default for RealtimeConfig {
    fn default() -> Self {
        Self {
            response_threshold: 0.5,
            voice_thickness: 0.0,
            index_rate: 0.5,
            rms_mix_rate: 0.25,
            protect: 0.33,
            loudness: 1.0,
            f0_method: "rmvpe".into(),
            f0_filter_radius: 3,
            resample_sr: 0,
            sample_rate_mode: "device".into(),
            custom_sample_rate: 48_000,
            chunk_size: 4096,
            harvest_processes: 2,
            crossfade_ms: 10,
            extra_inference_ms: 2500,
            buffer_ms: 500,
        }
    }
}

impl Default for StartConfig {
    fn default() -> Self {
        Self {
            input_device: None,
            output_device: None,
            voice_id: "yujie".into(),
            pitch_shift: 0,
            sidecar_ws_url: "ws://127.0.0.1:8765/stream".into(),
            chunk_size: 4096,
            latency_secs: 0.5,
            realtime_config: RealtimeConfig::default(),
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
    profile: Arc<RwLock<Option<RealtimeProfile>>>,
    stop_tx: Option<mpsc::Sender<()>>,
    control_tx: Option<mpsc::Sender<EngineControl>>,
}

enum EngineControl {
    SetVoice(String),
    SetPitch(i32),
    SetRealtimeConfig(RealtimeConfig),
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
            profile: Arc::new(RwLock::new(None)),
            stop_tx: None,
            control_tx: None,
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

    pub fn profile(&self) -> Option<RealtimeProfile> {
        self.profile.read().clone()
    }

    pub async fn start(&mut self, cfg: StartConfig, dsp: SharedDspState) -> AppResult<()> {
        if matches!(self.status, EngineStatus::Running | EngineStatus::Starting) {
            return Ok(());
        }
        self.status = EngineStatus::Starting;
        tracing::info!(
            "启动音频引擎: voice={} pitch={}",
            cfg.voice_id,
            cfg.pitch_shift
        );

        let desired_sample_rate = if cfg.realtime_config.sample_rate_mode == "custom" {
            Some(cfg.realtime_config.custom_sample_rate)
        } else {
            None
        };

        let ring_sample_rate = desired_sample_rate.unwrap_or(DEFAULT_RING_SAMPLE_RATE);

        // 1) 先建采集流，确认采样率
        let mic_ring = AudioRingBuffer::new(ring_sample_rate, 1, cfg.latency_secs);
        let (mic_prod, mut mic_cons) = mic_ring.split();
        let cap = match build_capture_stream(
            cfg.input_device.as_deref(),
            mic_prod,
            desired_sample_rate,
        ) {
            Ok(cap) => cap,
            Err(e) => {
                self.status = EngineStatus::Stopped;
                return Err(e);
            }
        };
        self.capture_level = cap.level_meter.clone();

        // 2) 建输出流
        let out_ring = AudioRingBuffer::new(ring_sample_rate, 1, cfg.latency_secs);
        let (mut out_prod, out_cons) = out_ring.split();
        let out_stream = match build_output_stream(
            cfg.output_device.as_deref(),
            out_cons,
            desired_sample_rate,
        ) {
            Ok(stream) => stream,
            Err(e) => {
                self.capture = None;
                self.status = EngineStatus::Stopped;
                return Err(e);
            }
        };

        // 3) 连接 sidecar WebSocket，优先协商 shared-memory PCM。
        let mut client = match SidecarClient::connect(&cfg.sidecar_ws_url).await {
            Ok(client) => client,
            Err(e) => {
                self.capture = None;
                self.output = None;
                self.status = EngineStatus::Stopped;
                return Err(e);
            }
        };
        let shm_capacity = (ring_sample_rate as usize * SHM_RING_SECS).max(cfg.chunk_size * 8);
        let shm_base = std::env::temp_dir().join(format!(
            "fuck-rvc-{}-{}",
            std::process::id(),
            uuid::Uuid::new_v4()
        ));
        let shm_input = ShmRing::create(shm_base.with_extension("in.pcm"), shm_capacity).ok();
        let shm_output = ShmRing::create(shm_base.with_extension("out.pcm"), shm_capacity).ok();
        let shm_cfg = match (&shm_input, &shm_output) {
            (Some(input), Some(output)) => Some(ShmInitConfig {
                input_path: input.path().to_string_lossy().to_string(),
                output_path: output.path().to_string_lossy().to_string(),
                capacity_samples: input.capacity().min(output.capacity()),
            }),
            _ => None,
        };

        if let Err(e) = client
            .send_init(
                &cfg.voice_id,
                cfg.pitch_shift,
                cap.sample_rate,
                out_stream.sample_rate,
                &cfg.realtime_config,
                shm_cfg.as_ref(),
            )
            .await
        {
            self.capture = None;
            self.output = None;
            self.status = EngineStatus::Stopped;
            return Err(e);
        }
        let use_shm = match client.wait_ready(SIDECAR_READY_TIMEOUT).await {
            Ok(use_shm) => use_shm && shm_input.is_some() && shm_output.is_some(),
            Err(e) => {
                self.capture = None;
                self.output = None;
                self.status = EngineStatus::Stopped;
                return Err(e);
            }
        };
        tracing::info!("sidecar transport={}", if use_shm { "shm" } else { "websocket" });

        // 4) 启动两个 tokio 任务：
        //    a) 从 mic_ring 弹 chunk → 经 DSP（降噪 + VAD）→ 发 sidecar；
        //       如果 VAD 判定为静音，跳过发送（节省 GPU / 带宽）。
        //    b) 把 sidecar 返回的数据写入 out_ring。
        let (stop_tx, mut stop_rx) = mpsc::channel::<()>(1);
        let (control_tx, mut control_rx) = mpsc::channel::<EngineControl>(8);
        let chunk = cfg.chunk_size;
        let (mut to_sidecar, mut from_sidecar) = client.split();
        let mut shm_input = if use_shm { shm_input } else { None };
        let mut shm_output = if use_shm { shm_output } else { None };

        let capture_sr = cap.sample_rate;
        let dsp_for_task = dsp.clone();
        let profile_for_send = self.profile.clone();
        let send_task = tokio::spawn(async move {
            let mut buf = vec![0.0_f32; chunk];
            let mut dsp_out: Vec<f32> = Vec::with_capacity(chunk * 2);
            let mut speech_burst: Vec<f32> = Vec::with_capacity(chunk * 4);
            let mut pre_roll = VecDeque::with_capacity(capture_sr as usize * VAD_PREROLL_MS / 1000);
            let pre_roll_capacity = capture_sr as usize * VAD_PREROLL_MS / 1000;
            let mut was_speaking = false;
            let mut processor = DspProcessor::new(capture_sr, dsp_for_task);
            loop {
                tokio::select! {
                    _ = stop_rx.recv() => break,
                    cmd = control_rx.recv() => {
                        match cmd {
                            Some(EngineControl::SetVoice(voice_id)) => {
                                if let Err(e) = to_sidecar.set_voice(&voice_id).await {
                                    tracing::warn!("切换 sidecar 音色失败: {e}");
                                    break;
                                }
                                processor.reset();
                                pre_roll.clear();
                                was_speaking = false;
                            }
                            Some(EngineControl::SetPitch(pitch)) => {
                                if let Err(e) = to_sidecar.set_pitch(pitch).await {
                                    tracing::warn!("设置 sidecar 音高失败: {e}");
                                    break;
                                }
                            }
                            Some(EngineControl::SetRealtimeConfig(config)) => {
                                if let Err(e) = to_sidecar.set_realtime_config(&config).await {
                                    tracing::warn!("设置 sidecar 实时参数失败: {e}");
                                    break;
                                }
                            }
                            None => break,
                        }
                    }
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
                        let dsp_started = Instant::now();
                        dsp_out.clear();
                        let speaking = processor.process(&buf[..filled], &mut dsp_out);
                        update_profile(&profile_for_send, |profile| {
                            profile.rust_dsp_ms = Some(elapsed_ms(dsp_started));
                            profile.chunk_samples = Some(filled as u32);
                        });
                        if dsp_out.is_empty() {
                            continue;
                        }
                        if !speaking {
                            push_preroll(&mut pre_roll, &dsp_out, pre_roll_capacity);
                            was_speaking = false;
                            continue;
                        }

                        let samples = if was_speaking || pre_roll.is_empty() {
                            &dsp_out
                        } else {
                            speech_burst.clear();
                            speech_burst.extend(pre_roll.drain(..));
                            speech_burst.extend_from_slice(&dsp_out);
                            &speech_burst
                        };
                        was_speaking = true;

                        let send_started = Instant::now();
                        let transport = if let Some(input) = shm_input.as_mut() {
                            let written = input.write_lossy(samples);
                            if let Err(e) = to_sidecar.notify_shm_audio(written).await {
                                tracing::warn!("通知 sidecar shm 音频失败: {e}");
                                break;
                            }
                            "shm"
                        } else {
                            if let Err(e) = to_sidecar.send_audio(samples).await {
                                tracing::warn!("发送到 sidecar 失败: {e}");
                                break;
                            }
                            "websocket"
                        };
                        update_profile(&profile_for_send, |profile| {
                            profile.rust_send_ms = Some(elapsed_ms(send_started));
                            profile.transport = Some(transport.into());
                        });
                    }
                }
            }
        });

        let output_level = self.output_level.clone();
        let profile_state = self.profile.clone();
        let recv_task = tokio::spawn(async move {
            let mut shm_out_buf: Vec<f32> = Vec::with_capacity(chunk * 2);
            loop {
                if let Some(output) = shm_output.as_mut() {
                    let output_started = Instant::now();
                    let read = output.read_into(&mut shm_out_buf, chunk * 4);
                    if read > 0 {
                        let mut peak = 0.0_f32;
                        for &sample in &shm_out_buf {
                            if sample.abs() > peak {
                                peak = sample.abs();
                            }
                            let _ = ringbuf::traits::Producer::try_push(&mut out_prod, sample);
                        }
                        update_profile(&profile_state, |profile| {
                            profile.rust_output_ms = Some(elapsed_ms(output_started));
                            profile.transport = Some("shm".into());
                        });
                        let mut g = output_level.lock();
                        *g = 0.8 * *g + 0.2 * peak;
                        continue;
                    }
                    tokio::select! {
                        frame = from_sidecar.next_frame() => {
                            match frame {
                                Some(Ok(SidecarFrame::Status(state))) => tracing::debug!("sidecar status: {state}"),
                                Some(Ok(SidecarFrame::Profile(profile))) => {
                                    update_profile(&profile_state, |state| {
                                        let rust_dsp_ms = state.rust_dsp_ms;
                                        let rust_send_ms = state.rust_send_ms;
                                        let rust_output_ms = state.rust_output_ms;
                                        let chunk_samples = state.chunk_samples.or(profile.chunk_samples);
                                        let transport = state.transport.clone().or(profile.transport.clone());
                                        *state = profile;
                                        state.rust_dsp_ms = rust_dsp_ms;
                                        state.rust_send_ms = rust_send_ms;
                                        state.rust_output_ms = rust_output_ms;
                                        state.chunk_samples = chunk_samples;
                                        state.transport = transport;
                                    });
                                }
                                Some(Ok(SidecarFrame::Error(message))) => tracing::warn!("sidecar error: {message}"),
                                Some(Ok(SidecarFrame::AudioBytes(_))) => {}
                                Some(Err(e)) => {
                                    tracing::warn!("sidecar 帧解析错误: {e}");
                                    break;
                                }
                                None => break,
                            }
                        }
                        _ = tokio::time::sleep(std::time::Duration::from_millis(2)) => {}
                    }
                    continue;
                }

                let Some(frame) = from_sidecar.next_frame().await else {
                    break;
                };
                match frame {
                    Ok(SidecarFrame::AudioBytes(bytes)) => {
                        let output_started = Instant::now();
                        let mut peak = 0.0_f32;
                        let samples = bytemuck::cast_slice::<u8, f32>(&bytes);
                        for &sample in samples {
                            if sample.abs() > peak {
                                peak = sample.abs();
                            }
                            let _ = ringbuf::traits::Producer::try_push(&mut out_prod, sample);
                        }
                        let mut g = output_level.lock();
                        *g = 0.8 * *g + 0.2 * peak;
                        update_profile(&profile_state, |profile| {
                            profile.rust_output_ms = Some(elapsed_ms(output_started));
                            profile.transport = Some("websocket".into());
                        });
                    }
                    Ok(SidecarFrame::Status(state)) => {
                        tracing::debug!("sidecar status: {state}");
                    }
                    Ok(SidecarFrame::Profile(profile)) => {
                        update_profile(&profile_state, |state| {
                            let rust_dsp_ms = state.rust_dsp_ms;
                            let rust_send_ms = state.rust_send_ms;
                            let rust_output_ms = state.rust_output_ms;
                            let chunk_samples = state.chunk_samples.or(profile.chunk_samples);
                            let transport = state.transport.clone().or(profile.transport.clone());
                            *state = profile;
                            state.rust_dsp_ms = rust_dsp_ms;
                            state.rust_send_ms = rust_send_ms;
                            state.rust_output_ms = rust_output_ms;
                            state.chunk_samples = chunk_samples;
                            state.transport = transport;
                        });
                    }
                    Ok(SidecarFrame::Error(message)) => {
                        tracing::warn!("sidecar error: {message}");
                    }
                    Err(e) => {
                        tracing::warn!("sidecar 帧解析错误: {e}");
                        break;
                    }
                }
            }
        });

        self.capture = Some(cap);
        self.output = Some(out_stream);
        *self.profile.write() = None;
        self.tasks = vec![send_task, recv_task];
        self.stop_tx = Some(stop_tx);
        self.control_tx = Some(control_tx);
        self.status = EngineStatus::Running;
        Ok(())
    }

    pub async fn set_voice(&self, voice_id: String) -> AppResult<()> {
        match self.status {
            EngineStatus::Running | EngineStatus::Starting => {
                let tx = self
                    .control_tx
                    .as_ref()
                    .ok_or_else(|| AppError::AudioStream("音频引擎控制通道未初始化".into()))?;
                tx.send(EngineControl::SetVoice(voice_id))
                    .await
                    .map_err(|_| AppError::AudioStream("音频引擎控制通道已关闭".into()))
            }
            _ => Ok(()),
        }
    }

    pub async fn set_pitch(&self, semitones: i32) -> AppResult<()> {
        match self.status {
            EngineStatus::Running | EngineStatus::Starting => {
                let tx = self
                    .control_tx
                    .as_ref()
                    .ok_or_else(|| AppError::AudioStream("音频引擎控制通道未初始化".into()))?;
                tx.send(EngineControl::SetPitch(semitones))
                    .await
                    .map_err(|_| AppError::AudioStream("音频引擎控制通道已关闭".into()))
            }
            _ => Ok(()),
        }
    }

    pub async fn set_realtime_config(&self, config: RealtimeConfig) -> AppResult<()> {
        match self.status {
            EngineStatus::Running | EngineStatus::Starting => {
                let tx = self
                    .control_tx
                    .as_ref()
                    .ok_or_else(|| AppError::AudioStream("音频引擎控制通道未初始化".into()))?;
                tx.send(EngineControl::SetRealtimeConfig(config))
                    .await
                    .map_err(|_| AppError::AudioStream("音频引擎控制通道已关闭".into()))
            }
            _ => Ok(()),
        }
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
        self.control_tx = None;
        for t in self.tasks.drain(..) {
            t.abort();
        }
        self.capture = None;
        self.output = None;
        *self.profile.write() = None;
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

fn push_preroll(pre_roll: &mut VecDeque<f32>, samples: &[f32], capacity: usize) {
    if capacity == 0 || samples.is_empty() {
        return;
    }
    if samples.len() >= capacity {
        pre_roll.clear();
        pre_roll.extend(samples[samples.len() - capacity..].iter().copied());
        return;
    }

    let overflow = pre_roll
        .len()
        .saturating_add(samples.len())
        .saturating_sub(capacity);
    for _ in 0..overflow {
        pre_roll.pop_front();
    }
    pre_roll.extend(samples.iter().copied());
}

fn update_profile(
    profile_state: &Arc<RwLock<Option<RealtimeProfile>>>,
    update: impl FnOnce(&mut RealtimeProfile),
) {
    let mut guard = profile_state.write();
    if guard.is_none() {
        *guard = Some(RealtimeProfile::default());
    }
    if let Some(profile) = guard.as_mut() {
        update(profile);
    }
}

fn elapsed_ms(start: Instant) -> f32 {
    start.elapsed().as_secs_f32() * 1000.0
}
