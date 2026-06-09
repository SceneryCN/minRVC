//! Tauri 命令层。每个文件对应前端一组 invoke 入口。
//!
//! 命名约定：snake_case，前端用 `invoke('list_input_devices')` 调用。
//! 错误统一返回 `AppError`，序列化为字符串。

pub mod audio_cmds;
pub mod dsp_cmds;
pub mod engine_cmds;
pub mod model_cmds;
pub mod separation_cmds;
pub mod training_cmds;
