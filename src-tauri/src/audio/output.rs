//! 输出流：把变声后的 PCM 喂给 VB-Cable / BlackHole。
//!
//! 关键点：
//! - 输入是 mono f32（来自 sidecar），输出可能是 stereo / 多通道
//! - 简单复制到所有通道（mono -> N ch）
//! - 队列空时输出静音，避免爆音

use crate::audio::ring::SampleConsumer;
use crate::audio::send_stream::SendStream;
use crate::error::{AppError, AppResult};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, Stream, StreamConfig};
use ringbuf::traits::Consumer;

pub struct OutputStream {
    _stream: SendStream,
    pub sample_rate: u32,
}

pub fn build_output_stream(
    device_name: Option<&str>,
    consumer: SampleConsumer,
    desired_sample_rate: Option<u32>,
) -> AppResult<OutputStream> {
    let host = cpal::default_host();
    let device = pick_output_device(&host, device_name)?;

    let supported = device
        .default_output_config()
        .map_err(|e| AppError::AudioDevice(format!("default_output_config: {e}")))?;
    let sample_rate = desired_sample_rate.unwrap_or_else(|| supported.sample_rate().0);
    let channels = supported.channels();
    let sample_format = supported.sample_format();
    let mut cfg: StreamConfig = supported.into();
    cfg.sample_rate = cpal::SampleRate(sample_rate);

    tracing::info!(
        "输出流：device={:?} sr={} ch={} fmt={:?}",
        device.name().ok(),
        sample_rate,
        channels,
        sample_format
    );

    let stream = build_stream_inner(&device, &cfg, sample_format, consumer, channels)?;
    stream
        .play()
        .map_err(|e| AppError::AudioStream(format!("output play: {e}")))?;

    Ok(OutputStream {
        _stream: SendStream::new(stream),
        sample_rate,
    })
}

fn pick_output_device(host: &cpal::Host, name: Option<&str>) -> AppResult<Device> {
    if let Some(target) = name {
        for d in host
            .output_devices()
            .map_err(|e| AppError::AudioDevice(e.to_string()))?
        {
            if d.name().ok().as_deref() == Some(target) {
                return Ok(d);
            }
        }
    }
    host.default_output_device()
        .ok_or_else(|| AppError::AudioDevice("没有可用的输出设备".into()))
}

fn build_stream_inner(
    device: &Device,
    cfg: &StreamConfig,
    fmt: SampleFormat,
    mut consumer: SampleConsumer,
    channels: u16,
) -> AppResult<Stream> {
    let err_fn = |e| tracing::error!("output stream error: {e}");
    let ch = channels as usize;

    let stream = match fmt {
        SampleFormat::F32 => device.build_output_stream(
            cfg,
            move |data: &mut [f32], _| {
                fill_mono_to_n(data, ch, &mut consumer);
            },
            err_fn,
            None,
        ),
        SampleFormat::I16 => device.build_output_stream(
            cfg,
            move |data: &mut [i16], _| {
                fill_mono_to_i16(data, ch, &mut consumer);
            },
            err_fn,
            None,
        ),
        SampleFormat::U16 => device.build_output_stream(
            cfg,
            move |data: &mut [u16], _| {
                fill_mono_to_u16(data, ch, &mut consumer);
            },
            err_fn,
            None,
        ),
        other => {
            return Err(AppError::AudioStream(format!(
                "不支持的输出格式: {other:?}"
            )));
        }
    };

    stream.map_err(|e| AppError::AudioStream(format!("build_output_stream: {e}")))
}

fn fill_mono_to_n(out: &mut [f32], channels: usize, consumer: &mut SampleConsumer) {
    if channels == 0 {
        return;
    }
    let frames = out.len() / channels;
    for i in 0..frames {
        let mono = consumer.try_pop().unwrap_or(0.0);
        for c in 0..channels {
            out[i * channels + c] = mono;
        }
    }
}

fn fill_mono_to_i16(out: &mut [i16], channels: usize, consumer: &mut SampleConsumer) {
    if channels == 0 {
        return;
    }
    let frames = out.len() / channels;
    for i in 0..frames {
        let mono = consumer.try_pop().unwrap_or(0.0);
        let sample = (mono.clamp(-1.0, 1.0) * i16::MAX as f32) as i16;
        for c in 0..channels {
            out[i * channels + c] = sample;
        }
    }
}

fn fill_mono_to_u16(out: &mut [u16], channels: usize, consumer: &mut SampleConsumer) {
    if channels == 0 {
        return;
    }
    let frames = out.len() / channels;
    for i in 0..frames {
        let mono = consumer.try_pop().unwrap_or(0.0);
        let sample = ((mono.clamp(-1.0, 1.0) * 32767.0) + 32768.0) as u16;
        for c in 0..channels {
            out[i * channels + c] = sample;
        }
    }
}
