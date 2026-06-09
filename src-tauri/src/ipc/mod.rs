//! 与 Python sidecar 的 IPC 协议。
//!
//! 选择 WebSocket 而非 stdin/stdout：
//! - 二进制帧天然支持，传 PCM f32 不需要 base64
//! - 重连/心跳/状态消息混合传输容易
//! - 跨平台（Windows/macOS/Linux）一致
//!
//! 协议（简化版）：
//! - 客户端 → 服务端：
//!     {"type":"init","voice_id":"yujie","pitch":0,"in_sr":48000,"out_sr":48000}  // text
//!     <PCM f32 LE bytes>                                                          // binary
//!     {"type":"set_voice","voice_id":"loli"}                                      // text
//! - 服务端 → 客户端：
//!     {"type":"ready"}                                                            // text
//!     <PCM f32 LE bytes>                                                          // binary
//!     {"type":"error","message":"..."}                                            // text

pub mod ws_client;
pub mod shm_ring;
