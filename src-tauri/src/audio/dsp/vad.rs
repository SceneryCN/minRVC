//! Silero VAD（Voice Activity Detection）封装。
//!
//! - 输入：16 kHz mono f32
//! - 帧大小：512 sample（约 32 ms）
//! - 输出：每帧一个 [0, 1] 概率值；外部状态机做防抖（min_speech / min_silence）
//!
//! 注意：silero-vad-rust 内部使用 `ort` 加载 ONNX，模型权重已捆绑在 crate 里，
//! 启动时不会触发任何网络请求。

use silero_vad_rust::silero_vad::model::{load_silero_vad, OnnxModel};

pub const SILERO_FRAME: usize = 512;
pub const SILERO_SR: u32 = 16_000;
const FRAME_MS: u32 = 32; // 512 / 16000 ≈ 32 ms

pub struct SileroVadDetector {
    model: OnnxModel,
    /// 16 kHz 输入累积缓冲；满 512 才推理一帧
    buf: Vec<f32>,
    last_prob: f32,
    speaking: bool,
    speech_frames: u32,
    silence_frames: u32,
    threshold: f32,
    min_speech_frames: u32,
    min_silence_frames: u32,
}

impl SileroVadDetector {
    pub fn new(threshold: f32, min_speech_ms: u32, min_silence_ms: u32) -> Result<Self, String> {
        let model = load_silero_vad().map_err(|e| format!("加载 Silero VAD 模型失败: {e}"))?;
        Ok(Self {
            model,
            buf: Vec::with_capacity(SILERO_FRAME),
            last_prob: 0.0,
            speaking: false,
            speech_frames: 0,
            silence_frames: 0,
            threshold: threshold.clamp(0.0, 1.0),
            min_speech_frames: ms_to_frames(min_speech_ms),
            min_silence_frames: ms_to_frames(min_silence_ms),
        })
    }

    pub fn set_threshold(&mut self, t: f32) {
        self.threshold = t.clamp(0.0, 1.0);
    }

    pub fn set_min_speech_ms(&mut self, ms: u32) {
        self.min_speech_frames = ms_to_frames(ms);
    }

    pub fn set_min_silence_ms(&mut self, ms: u32) {
        self.min_silence_frames = ms_to_frames(ms);
    }

    /// 喂入 16 kHz mono 样本，内部累计 512 一帧推理。
    pub fn feed(&mut self, samples_16k: &[f32]) {
        for &s in samples_16k {
            self.buf.push(s);
            if self.buf.len() == SILERO_FRAME {
                if let Ok(probs) = self.model.forward_chunk(&self.buf, SILERO_SR) {
                    let p = probs[[0, 0]];
                    self.update_state_machine(p);
                }
                self.buf.clear();
            }
        }
    }

    fn update_state_machine(&mut self, prob: f32) {
        self.last_prob = prob;
        if prob >= self.threshold {
            self.speech_frames = self.speech_frames.saturating_add(1);
            self.silence_frames = 0;
            if !self.speaking && self.speech_frames >= self.min_speech_frames {
                self.speaking = true;
            }
        } else {
            self.silence_frames = self.silence_frames.saturating_add(1);
            self.speech_frames = 0;
            if self.speaking && self.silence_frames >= self.min_silence_frames {
                self.speaking = false;
            }
        }
    }

    pub fn is_speaking(&self) -> bool {
        self.speaking
    }

    pub fn last_probability(&self) -> f32 {
        self.last_prob
    }

    pub fn reset(&mut self) {
        self.buf.clear();
        self.last_prob = 0.0;
        self.speaking = false;
        self.speech_frames = 0;
        self.silence_frames = 0;
        // OnnxModel 内部 LSTM 状态我们没法重置（crate 不暴露），但开关一次后影响很小
    }
}

#[inline]
fn ms_to_frames(ms: u32) -> u32 {
    (ms / FRAME_MS).max(1)
}
