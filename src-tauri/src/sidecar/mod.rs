//! Python sidecar 进程管理。
//!
//! 两种模式：
//! 1. 开发模式：直接 `python -m rvc_engine.server`，需要环境里有 Python + 依赖
//! 2. 生产模式：调用 PyInstaller 打包出来的 `rvc-sidecar` 可执行文件
//!
//! 通过 Tauri 的 sidecar 机制（`tauri::process::CommandChild`）管理进程生命周期。

mod manager;
pub use manager::SidecarManager;
