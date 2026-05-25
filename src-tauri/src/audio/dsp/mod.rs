//! 实时 DSP（数字信号处理）子系统：降噪 + VAD。
//!
//! 数据流：
//!   capture (任意采样率，通常 48kHz mono f32)
//!     → 降噪 (RNNoise，纯 Rust，10ms/帧 @ 48kHz)
//!     → VAD (Silero ONNX，32ms/帧 @ 16kHz；下采用)
//!     → ringbuf → sidecar
//!
//! 设计：
//! - DSP 跑在 send_task tokio 任务里，与音频回调解耦（cpal 回调禁止 alloc/阻塞）
//! - 降噪与 VAD 都可独立开关；VAD 判定为静音时 chunk 直接丢弃，省 GPU
//! - 共享配置与状态通过 `SharedDspState` 暴露给前端 IPC 命令
//! - 第一版 backend：nnnoiseless + silero-vad-rust。后续可扩展 DeepFilterNet。

pub mod denoise;
pub mod processor;
pub mod state;
pub mod vad;

pub use processor::DspProcessor;
pub use state::{DspConfig, DspStatus, SharedDspState};
