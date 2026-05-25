//! WebSocket 客户端：连接到本地 Python sidecar。

use crate::error::{AppError, AppResult};
use futures_util::stream::SplitSink;
use futures_util::stream::SplitStream;
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use tokio::net::TcpStream;
use tokio_tungstenite::{
    tungstenite::Message, MaybeTlsStream, WebSocketStream,
};

type WsStream = WebSocketStream<MaybeTlsStream<TcpStream>>;

#[derive(Debug, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
enum ClientMessage<'a> {
    Init {
        voice_id: &'a str,
        pitch: i32,
        in_sr: u32,
        out_sr: u32,
    },
    SetVoice {
        voice_id: &'a str,
    },
    SetPitch {
        pitch: i32,
    },
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    Ready,
    Status { state: String },
    Error { message: String },
}

#[derive(Debug)]
pub enum SidecarFrame {
    Audio(Vec<f32>),
    Status(String),
    Error(String),
}

pub struct SidecarClient {
    inner: WsStream,
}

pub struct SidecarSender {
    sink: SplitSink<WsStream, Message>,
}

pub struct SidecarReceiver {
    stream: SplitStream<WsStream>,
}

impl SidecarClient {
    pub async fn connect(url: &str) -> AppResult<Self> {
        let (ws, _) = tokio_tungstenite::connect_async(url)
            .await
            .map_err(|e| AppError::WebSocket(format!("连接 {url} 失败: {e}")))?;
        Ok(Self { inner: ws })
    }

    pub async fn send_init(
        &mut self,
        voice_id: &str,
        pitch: i32,
        in_sr: u32,
        out_sr: u32,
    ) -> AppResult<()> {
        let msg = ClientMessage::Init {
            voice_id,
            pitch,
            in_sr,
            out_sr,
        };
        let json = serde_json::to_string(&msg)?;
        self.inner
            .send(Message::Text(json.into()))
            .await
            .map_err(|e| AppError::WebSocket(e.to_string()))?;
        Ok(())
    }

    pub fn split(self) -> (SidecarSender, SidecarReceiver) {
        let (sink, stream) = self.inner.split();
        (SidecarSender { sink }, SidecarReceiver { stream })
    }
}

impl SidecarSender {
    pub async fn send_audio(&mut self, samples: &[f32]) -> AppResult<()> {
        let mut bytes = Vec::with_capacity(samples.len() * 4);
        for s in samples {
            bytes.extend_from_slice(&s.to_le_bytes());
        }
        self.sink
            .send(Message::Binary(bytes.into()))
            .await
            .map_err(|e| AppError::WebSocket(e.to_string()))?;
        Ok(())
    }

    pub async fn set_voice(&mut self, voice_id: &str) -> AppResult<()> {
        let msg = ClientMessage::SetVoice { voice_id };
        let json = serde_json::to_string(&msg)?;
        self.sink
            .send(Message::Text(json.into()))
            .await
            .map_err(|e| AppError::WebSocket(e.to_string()))?;
        Ok(())
    }

    pub async fn set_pitch(&mut self, pitch: i32) -> AppResult<()> {
        let msg = ClientMessage::SetPitch { pitch };
        let json = serde_json::to_string(&msg)?;
        self.sink
            .send(Message::Text(json.into()))
            .await
            .map_err(|e| AppError::WebSocket(e.to_string()))?;
        Ok(())
    }
}

impl SidecarReceiver {
    pub async fn next_frame(&mut self) -> Option<AppResult<SidecarFrame>> {
        let msg = self.stream.next().await?;
        match msg {
            Ok(Message::Binary(bytes)) => {
                if bytes.len() % 4 != 0 {
                    return Some(Err(AppError::WebSocket("二进制长度不是 4 的倍数".into())));
                }
                let mut samples = Vec::with_capacity(bytes.len() / 4);
                for chunk in bytes.chunks_exact(4) {
                    let v = f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
                    samples.push(v);
                }
                Some(Ok(SidecarFrame::Audio(samples)))
            }
            Ok(Message::Text(text)) => {
                match serde_json::from_str::<ServerMessage>(&text) {
                    Ok(ServerMessage::Ready) => Some(Ok(SidecarFrame::Status("ready".into()))),
                    Ok(ServerMessage::Status { state }) => Some(Ok(SidecarFrame::Status(state))),
                    Ok(ServerMessage::Error { message }) => Some(Ok(SidecarFrame::Error(message))),
                    Err(e) => Some(Err(AppError::WebSocket(format!("反序列化失败: {e}")))),
                }
            }
            Ok(Message::Close(_)) => None,
            Ok(_) => Some(Ok(SidecarFrame::Status("ping".into()))),
            Err(e) => Some(Err(AppError::WebSocket(e.to_string()))),
        }
    }
}
