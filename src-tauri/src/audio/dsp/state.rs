//! 共享 DSP 配置 / 状态。
//!
//! - `DspConfig`：用户可调参数（开关、强度、VAD 阈值等）
//! - `DspStatus`：实时状态（是否在说话、最近 VAD 概率等）
//!
//! 通过 `Arc<RwLock<>>` 在「前端命令线程」与「send_task tokio 任务」之间共享。

use parking_lot::RwLock;
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DspConfig {
    /// 是否开启实时降噪
    pub denoise_enabled: bool,
    /// 降噪强度（0.0=完全保留原始信号 / 1.0=完全降噪输出）
    pub denoise_strength: f32,
    /// 是否开启 VAD（静音段不送 sidecar，省 GPU）
    pub vad_enabled: bool,
    /// VAD 阈值（0.0~1.0，越高越严格）
    pub vad_threshold: f32,
    /// 持续多少 ms 概率超过阈值才判定为「开始说话」（防抖）
    pub vad_min_speech_ms: u32,
    /// 持续多少 ms 概率低于阈值才判定为「停止说话」
    pub vad_min_silence_ms: u32,
}

impl Default for DspConfig {
    fn default() -> Self {
        Self {
            denoise_enabled: true,
            denoise_strength: 1.0,
            vad_enabled: true,
            vad_threshold: 0.5,
            vad_min_speech_ms: 250,
            vad_min_silence_ms: 250,
        }
    }
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DspStatus {
    /// 当前是否被判定为「正在说话」
    pub speaking: bool,
    /// 最近一帧 VAD 概率（0.0~1.0，仅供 UI 可视化）
    pub vad_probability: f32,
    /// 降噪是否在生效（开关 + 采样率匹配）
    pub denoise_active: bool,
    /// VAD 模块是否可用（ONNX 模型加载成功）
    pub vad_available: bool,
}

#[derive(Default, Clone)]
pub struct SharedDspState {
    config: Arc<RwLock<DspConfig>>,
    status: Arc<RwLock<DspStatus>>,
}

impl SharedDspState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn config(&self) -> DspConfig {
        *self.config.read()
    }

    pub fn set_config(&self, cfg: DspConfig) {
        *self.config.write() = cfg;
    }

    pub fn status(&self) -> DspStatus {
        *self.status.read()
    }

    pub fn update_status<F: FnOnce(&mut DspStatus)>(&self, f: F) {
        let mut s = self.status.write();
        f(&mut s);
    }
}
