//! 麦克风采集流。
//!
//! 关键点：
//! - cpal 回调跑在专用音频线程，禁止做任何分配 / 阻塞操作
//! - 数据全部以 f32 单声道 PCM 形式压入 SPSC 环形缓冲
//! - 多声道输入会自动 downmix 为单声道（取均值），降低后续推理成本
//! - 重采样统一交给 Python sidecar 处理（HuBERT 通常吃 16kHz）

use crate::audio::ring::SampleProducer;
use crate::audio::send_stream::SendStream;
use crate::error::{AppError, AppResult};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, Stream, StreamConfig};
use parking_lot::Mutex;
use ringbuf::traits::Producer;
use std::sync::Arc;

pub struct CaptureStream {
    _stream: SendStream,
    pub sample_rate: u32,
    pub level_meter: Arc<Mutex<f32>>,
}

pub fn build_capture_stream(
    device_name: Option<&str>,
    producer: SampleProducer,
    desired_sample_rate: Option<u32>,
) -> AppResult<CaptureStream> {
    let host = cpal::default_host();
    let device = pick_input_device(&host, device_name)?;

    let supported = device
        .default_input_config()
        .map_err(|e| AppError::AudioDevice(format!("default_input_config: {e}")))?;
    let sample_rate = desired_sample_rate.unwrap_or_else(|| supported.sample_rate().0);
    let channels = supported.channels();
    let sample_format = supported.sample_format();
    let mut cfg: StreamConfig = supported.into();
    cfg.sample_rate = cpal::SampleRate(sample_rate);

    tracing::info!(
        "采集流：device={:?} sr={} ch={} fmt={:?}",
        device.name().ok(),
        sample_rate,
        channels,
        sample_format
    );

    let level_meter = Arc::new(Mutex::new(0.0_f32));
    let stream = build_stream_inner(
        &device,
        &cfg,
        sample_format,
        producer,
        channels,
        level_meter.clone(),
    )?;
    stream
        .play()
        .map_err(|e| AppError::AudioStream(format!("capture play: {e}")))?;

    Ok(CaptureStream {
        _stream: SendStream::new(stream),
        sample_rate,
        level_meter,
    })
}

fn pick_input_device(host: &cpal::Host, name: Option<&str>) -> AppResult<Device> {
    if let Some(target) = name {
        for d in host
            .input_devices()
            .map_err(|e| AppError::AudioDevice(e.to_string()))?
        {
            if d.name().ok().as_deref() == Some(target) {
                return Ok(d);
            }
        }
    }
    host.default_input_device()
        .ok_or_else(|| AppError::AudioDevice("没有可用的输入设备".into()))
}

fn build_stream_inner(
    device: &Device,
    cfg: &StreamConfig,
    fmt: SampleFormat,
    mut producer: SampleProducer,
    channels: u16,
    level_meter: Arc<Mutex<f32>>,
) -> AppResult<Stream> {
    let err_fn = |e| tracing::error!("capture stream error: {e}");

    let stream = match fmt {
        SampleFormat::F32 => device.build_input_stream(
            cfg,
            move |data: &[f32], _| {
                push_downmixed(data, channels, &mut producer, &level_meter);
            },
            err_fn,
            None,
        ),
        SampleFormat::I16 => device.build_input_stream(
            cfg,
            move |data: &[i16], _| {
                push_downmixed_i16(data, channels, &mut producer, &level_meter);
            },
            err_fn,
            None,
        ),
        SampleFormat::U16 => device.build_input_stream(
            cfg,
            move |data: &[u16], _| {
                push_downmixed_u16(data, channels, &mut producer, &level_meter);
            },
            err_fn,
            None,
        ),
        other => {
            return Err(AppError::AudioStream(format!(
                "不支持的采样格式: {other:?}"
            )));
        }
    };

    stream.map_err(|e| AppError::AudioStream(format!("build_input_stream: {e}")))
}

fn push_downmixed(
    data: &[f32],
    channels: u16,
    producer: &mut SampleProducer,
    level_meter: &Arc<Mutex<f32>>,
) {
    let ch = channels as usize;
    if ch == 0 {
        return;
    }
    let frames = data.len() / ch;
    let mut peak = 0.0_f32;
    for i in 0..frames {
        let mut sum = 0.0_f32;
        for c in 0..ch {
            sum += data[i * ch + c];
        }
        let mono = sum / ch as f32;
        if mono.abs() > peak {
            peak = mono.abs();
        }
        let _ = producer.try_push(mono);
    }
    let mut g = level_meter.lock();
    *g = 0.8 * *g + 0.2 * peak;
}

fn push_downmixed_i16(
    data: &[i16],
    channels: u16,
    producer: &mut SampleProducer,
    level_meter: &Arc<Mutex<f32>>,
) {
    let ch = channels as usize;
    if ch == 0 {
        return;
    }
    let frames = data.len() / ch;
    let mut peak = 0.0_f32;
    for i in 0..frames {
        let mut sum = 0.0_f32;
        for c in 0..ch {
            sum += data[i * ch + c] as f32 / i16::MAX as f32;
        }
        let mono = sum / ch as f32;
        if mono.abs() > peak {
            peak = mono.abs();
        }
        let _ = producer.try_push(mono);
    }
    let mut g = level_meter.lock();
    *g = 0.8 * *g + 0.2 * peak;
}

fn push_downmixed_u16(
    data: &[u16],
    channels: u16,
    producer: &mut SampleProducer,
    level_meter: &Arc<Mutex<f32>>,
) {
    let ch = channels as usize;
    if ch == 0 {
        return;
    }
    let frames = data.len() / ch;
    let mut peak = 0.0_f32;
    for i in 0..frames {
        let mut sum = 0.0_f32;
        for c in 0..ch {
            sum += (data[i * ch + c] as f32 - 32768.0) / 32768.0;
        }
        let mono = sum / ch as f32;
        if mono.abs() > peak {
            peak = mono.abs();
        }
        let _ = producer.try_push(mono);
    }
    let mut g = level_meter.lock();
    *g = 0.8 * *g + 0.2 * peak;
}
