//! 实时降噪后端：RNNoise（基于 nnnoiseless 纯 Rust 移植）。
//!
//! 关键点：
//! - 帧大小固定为 480 sample（10ms @ 48kHz），与 cpal chunk 大小不一定一致
//! - nnnoiseless 期望输入是 i16 范围的浮点（-32768..32767），需要 ×32768 / ÷32768
//! - 第一帧输出应当丢弃（参考 nnnoiseless 文档）
//! - 用「输入累积 + 输出队列」消除帧粒度差异，对外仅暴露 feed/pull 接口

use nnnoiseless::DenoiseState;
use std::collections::VecDeque;

/// RNNoise 帧大小（10ms @ 48kHz）。
pub const RNNOISE_FRAME: usize = 480;
/// RNNoise 期望的采样率。
pub const RNNOISE_SR: u32 = 48_000;

pub struct RnnoiseDenoiser {
    state: Box<DenoiseState<'static>>,
    in_buf: Vec<f32>,
    out_buf: VecDeque<f32>,
    discarded_first: bool,
    /// 0.0~1.0：与原信号混合比例。1.0=完全降噪输出
    strength: f32,
}

impl Default for RnnoiseDenoiser {
    fn default() -> Self {
        Self::new()
    }
}

impl RnnoiseDenoiser {
    pub fn new() -> Self {
        Self {
            state: DenoiseState::new(),
            in_buf: Vec::with_capacity(RNNOISE_FRAME),
            out_buf: VecDeque::with_capacity(RNNOISE_FRAME * 2),
            discarded_first: false,
            strength: 1.0,
        }
    }

    pub fn set_strength(&mut self, s: f32) {
        self.strength = s.clamp(0.0, 1.0);
    }

    /// 喂入 normalized [-1.0, 1.0] f32 mono 样本。
    /// 内部累计满 480 个样本后处理一帧。
    pub fn feed(&mut self, src: &[f32]) {
        for &sample in src {
            self.in_buf.push(sample);
            if self.in_buf.len() == RNNOISE_FRAME {
                self.process_one_frame();
            }
        }
    }

    fn process_one_frame(&mut self) {
        let mut frame_in = [0.0_f32; RNNOISE_FRAME];
        let mut frame_out = [0.0_f32; RNNOISE_FRAME];
        // RNNoise 约定：i16 范围浮点
        for i in 0..RNNOISE_FRAME {
            frame_in[i] = self.in_buf[i] * 32768.0;
        }
        self.state.process_frame(&mut frame_out, &frame_in);

        if !self.discarded_first {
            self.discarded_first = true;
            self.in_buf.clear();
            return;
        }

        let s = self.strength;
        let inv = 1.0 - s;
        for i in 0..RNNOISE_FRAME {
            let denoised = frame_out[i] / 32768.0;
            let mixed = denoised * s + self.in_buf[i] * inv;
            self.out_buf.push_back(mixed.clamp(-1.0, 1.0));
        }
        self.in_buf.clear();
    }

    /// 弹出 dst.len() 样本（不足则返回较少）。
    pub fn pull(&mut self, dst: &mut [f32]) -> usize {
        let mut n = 0;
        while n < dst.len() {
            match self.out_buf.pop_front() {
                Some(v) => {
                    dst[n] = v;
                    n += 1;
                }
                None => break,
            }
        }
        n
    }

    /// 当前 out 队列里待消费样本数。
    pub fn pending(&self) -> usize {
        self.out_buf.len()
    }

    pub fn reset(&mut self) {
        self.state = DenoiseState::new();
        self.in_buf.clear();
        self.out_buf.clear();
        self.discarded_first = false;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_sample_count() {
        let mut d = RnnoiseDenoiser::new();
        // 喂 5 帧 = 2400 样本，应当弹出 4 帧 = 1920（首帧丢弃）
        let input = vec![0.0_f32; RNNOISE_FRAME * 5];
        d.feed(&input);
        assert_eq!(d.pending(), RNNOISE_FRAME * 4);
        let mut out = vec![0.0_f32; RNNOISE_FRAME * 4];
        let n = d.pull(&mut out);
        assert_eq!(n, RNNOISE_FRAME * 4);
        assert_eq!(d.pending(), 0);
    }
}
