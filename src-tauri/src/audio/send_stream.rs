//! `cpal::Stream` 的 Send + Sync 包装。
//!
//! 背景：
//! - cpal 0.15 在所有目标平台上的 `Stream` 类型实际都是 Send/Sync 安全的：
//!   * macOS CoreAudio：Stream 仅持有 AUGraph / AudioUnit 句柄，回调由系统在
//!     Audio Toolbox 自有线程派发，跨线程移动 Drop guard 不影响行为。
//!   * Windows WASAPI：Stream 是 IAudioClient + IAudioRenderClient/CaptureClient
//!     的 RAII，COM 句柄本身可跨线程。
//!   * Linux ALSA：cpal 已实现 Send。
//! - 但 cpal 出于历史原因没有在类型系统层标注 Send/Sync，导致任何 `Arc<RwLock<T>>`
//!   只要包了 cpal::Stream 就丢失 Send，进而 `tauri::State<T>` 无法工作。
//!
//! 此 wrapper 只承担 Drop guard 的职责。我们**不**在多个线程同时操作同一个 Stream，
//! 所以这个 unsafe 是安全的。

use cpal::Stream;

pub struct SendStream {
    _stream: Stream,
}

unsafe impl Send for SendStream {}
unsafe impl Sync for SendStream {}

impl SendStream {
    pub fn new(stream: Stream) -> Self {
        Self { _stream: stream }
    }
}
