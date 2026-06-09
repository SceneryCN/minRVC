//! 音频子系统：
//! - `devices`:  设备枚举与虚拟声卡识别
//! - `capture`:  麦克风采集
//! - `output`:   虚拟声卡（VB-Cable）输出
//! - `ring`:     无锁环形缓冲（生产者-消费者）
//! - `engine`:   把 capture / output / sidecar IPC 串起来的引擎

pub mod capture;
pub mod devices;
pub mod dsp;
pub mod engine;
pub mod output;
pub mod ring;
pub mod send_stream;
