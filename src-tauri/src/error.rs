//! 全局错误类型。Tauri 命令返回 `Result<T, AppError>`，会被序列化为字符串给前端。

use serde::{Serialize, Serializer};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum AppError {
    #[error("音频设备错误: {0}")]
    AudioDevice(String),

    #[error("音频流错误: {0}")]
    AudioStream(String),

    #[error("Python sidecar 未启动或已退出")]
    SidecarNotRunning,

    #[error("Python sidecar 启动失败: {0}")]
    SidecarStart(String),

    #[error("WebSocket 连接错误: {0}")]
    WebSocket(String),

    #[error("模型未找到: {0}")]
    ModelNotFound(String),

    #[error("IO 错误: {0}")]
    Io(#[from] std::io::Error),

    #[error("JSON 解析错误: {0}")]
    Json(#[from] serde_json::Error),

    #[error("HTTP 请求错误: {0}")]
    Http(#[from] reqwest::Error),

    #[error("内部错误: {0}")]
    Internal(String),
}

impl Serialize for AppError {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.to_string())
    }
}

pub type AppResult<T> = Result<T, AppError>;
