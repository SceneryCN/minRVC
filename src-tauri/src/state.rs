//! 全局应用状态。
//!
//! 设计原则：
//! - 所有需要跨命令共享的句柄都放这里
//! - 通过 `Arc<Mutex>` / `Arc<RwLock>` 暴露，避免锁粒度过大
//! - Tauri 通过 `app.state::<AppState>()` 获取

use crate::audio::dsp::SharedDspState;
use crate::audio::engine::AudioEngine;
use crate::sidecar::SidecarManager;
use parking_lot::RwLock;
use std::sync::Arc;
use tokio::sync::Mutex as AsyncMutex;

/// 全局应用状态。
///
/// 锁选型：
/// - `audio_engine`：因为 start/stop 是 async（内部要 .await on tokio task spawn /
///   websocket 握手），用 tokio 的 `Mutex`，guard 是 Send 可以跨 await。
/// - `current_voice` / `pitch_shift`：纯 sync 字段，用 parking_lot 减少开销。
/// - `dsp`：内部已经自带 Arc<RwLock<>>，直接 clone 引用计数即可。
pub struct AppState {
    pub audio_engine: Arc<AsyncMutex<AudioEngine>>,
    pub sidecar: Arc<SidecarManager>,
    pub current_voice: Arc<RwLock<Option<String>>>,
    pub pitch_shift: Arc<RwLock<i32>>,
    pub dsp: SharedDspState,
}

impl Default for AppState {
    fn default() -> Self {
        Self::new()
    }
}

impl AppState {
    pub fn new() -> Self {
        Self {
            audio_engine: Arc::new(AsyncMutex::new(AudioEngine::new())),
            sidecar: Arc::new(SidecarManager::new()),
            current_voice: Arc::new(RwLock::new(None)),
            pitch_shift: Arc::new(RwLock::new(0)),
            dsp: SharedDspState::new(),
        }
    }
}
