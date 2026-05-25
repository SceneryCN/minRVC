//! DSP 处理器：把降噪、VAD 串成一条流式管线。
//!
//! 输入：任意采样率（通常 48 kHz） mono f32 [-1.0, 1.0]
//! 输出：写入 `out_buf`（可能少于输入，因为降噪首帧丢弃 / 帧粒度 480 累积）
//!
//! 决策：
//! - 降噪：只在 capture sr == 48 kHz 时启用（RNNoise 帧约束）。其它采样率 fallback 直通。
//! - VAD：通用，将信号下采到 16 kHz 后送 Silero。下采用简易 N:1 整数比平均（足够 VAD 用）。
//!   非整数比时 fallback：跳过 VAD（视为说话），避免 aliasing 影响判定。

use crate::audio::dsp::denoise::{RnnoiseDenoiser, RNNOISE_SR};
use crate::audio::dsp::state::SharedDspState;
use crate::audio::dsp::vad::{SileroVadDetector, SILERO_SR};

pub struct DspProcessor {
    sample_rate: u32,
    state: SharedDspState,
    denoise: Option<RnnoiseDenoiser>,
    vad: Option<SileroVadDetector>,
    /// VAD 下采用：sr / 16000 整数比；0 表示非整数比，禁用 VAD
    downsample_ratio: u32,
    downsample_acc: f32,
    downsample_count: u32,
    /// 复用：每次 process 累积 16k 样本喂 VAD
    scratch_16k: Vec<f32>,
}

impl DspProcessor {
    pub fn new(sample_rate: u32, state: SharedDspState) -> Self {
        let denoise = if sample_rate == RNNOISE_SR {
            Some(RnnoiseDenoiser::new())
        } else {
            tracing::warn!(
                "采样率 {} Hz ≠ 48 kHz，降噪暂时禁用（RNNoise 帧约束）",
                sample_rate
            );
            None
        };

        let cfg = state.config();
        let vad = match SileroVadDetector::new(
            cfg.vad_threshold,
            cfg.vad_min_speech_ms,
            cfg.vad_min_silence_ms,
        ) {
            Ok(v) => Some(v),
            Err(e) => {
                tracing::warn!("Silero VAD 初始化失败: {e}，VAD 将被禁用");
                None
            }
        };

        let downsample_ratio = if sample_rate >= SILERO_SR && sample_rate % SILERO_SR == 0 {
            sample_rate / SILERO_SR
        } else {
            0
        };
        if downsample_ratio == 0 {
            tracing::warn!(
                "采样率 {} Hz 与 16 kHz 非整数比，VAD 将被禁用",
                sample_rate
            );
        }

        // 同步可用性到共享 state
        state.update_status(|s| {
            s.vad_available = vad.is_some() && downsample_ratio > 0;
            s.denoise_active = denoise.is_some() && cfg.denoise_enabled;
        });

        Self {
            sample_rate,
            state,
            denoise,
            vad,
            downsample_ratio,
            downsample_acc: 0.0,
            downsample_count: 0,
            scratch_16k: Vec::with_capacity(2048),
        }
    }

    /// 处理 src（任意长度），降噪后输出追加到 out_buf；
    /// 返回当前 VAD 是否判定「正在说话」（VAD 关闭时永远返回 true）。
    pub fn process(&mut self, src: &[f32], out_buf: &mut Vec<f32>) -> bool {
        let cfg = self.state.config();

        // 1) 降噪（启用时）
        let denoised_len: usize = if cfg.denoise_enabled {
            if let Some(d) = &mut self.denoise {
                d.set_strength(cfg.denoise_strength);
                d.feed(src);
                let pending = d.pending();
                let start = out_buf.len();
                out_buf.resize(start + pending, 0.0);
                let n = d.pull(&mut out_buf[start..]);
                out_buf.truncate(start + n);
                self.state.update_status(|s| s.denoise_active = true);
                n
            } else {
                out_buf.extend_from_slice(src);
                self.state.update_status(|s| s.denoise_active = false);
                src.len()
            }
        } else {
            out_buf.extend_from_slice(src);
            self.state.update_status(|s| s.denoise_active = false);
            src.len()
        };

        // 2) VAD（基于降噪后输出片段判定）
        let vad_signal_start = out_buf.len() - denoised_len;
        let vad_signal = &out_buf[vad_signal_start..];
        let speaking = self.run_vad(vad_signal, &cfg);

        speaking
    }

    fn run_vad(&mut self, signal: &[f32], cfg: &crate::audio::dsp::state::DspConfig) -> bool {
        if !cfg.vad_enabled || self.downsample_ratio == 0 {
            self.state.update_status(|s| {
                s.speaking = true;
                s.vad_probability = 1.0;
            });
            return true;
        }
        let v = match &mut self.vad {
            Some(v) => v,
            None => {
                self.state.update_status(|s| {
                    s.speaking = true;
                    s.vad_probability = 1.0;
                });
                return true;
            }
        };

        v.set_threshold(cfg.vad_threshold);
        v.set_min_speech_ms(cfg.vad_min_speech_ms);
        v.set_min_silence_ms(cfg.vad_min_silence_ms);

        // 下采到 16 kHz：整数比简单平均
        self.scratch_16k.clear();
        let ratio = self.downsample_ratio;
        for &s in signal {
            self.downsample_acc += s;
            self.downsample_count += 1;
            if self.downsample_count >= ratio {
                self.scratch_16k
                    .push(self.downsample_acc / ratio as f32);
                self.downsample_acc = 0.0;
                self.downsample_count = 0;
            }
        }
        v.feed(&self.scratch_16k);

        let speaking = v.is_speaking();
        let prob = v.last_probability();
        self.state.update_status(|s| {
            s.speaking = speaking;
            s.vad_probability = prob;
        });
        speaking
    }

    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}
