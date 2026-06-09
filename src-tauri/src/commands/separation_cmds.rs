//! 离线人声分离命令。
//!
//! 把分离任务委托给 Python sidecar（HTTP API：/separate）。
//! Tauri 端只做：拉起 sidecar、转发请求、轮询状态、cancel。
//!
//! 设计：分离过程可能耗时 30s ~ 几分钟，前端通过 `get_separation_status` 轮询。

use crate::error::{AppError, AppResult};
use crate::state::AppState;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::State;

#[derive(Debug, Deserialize)]
pub struct StartSeparationPayload {
    /// 输入音频路径（本地文件系统绝对路径）
    pub input_path: String,
    /// 模型名（默认 htdemucs）
    pub model: Option<String>,
    /// 是否使用两段输出（vocals + accompaniment）；false 时输出 4-stem
    pub two_stems: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SeparationSession {
    pub session_id: String,
}

#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct SeparationStatus {
    pub session_id: String,
    pub state: String, // pending / running / done / failed / cancelled
    pub progress: f32, // 0.0 ~ 1.0
    pub message: Option<String>,
    pub vocals_path: Option<String>,
    pub other_path: Option<String>,
    pub error: Option<String>,
}

const HTTP_TIMEOUT: Duration = Duration::from_secs(8);

#[tauri::command]
pub async fn start_separation(
    state: State<'_, AppState>,
    payload: StartSeparationPayload,
) -> AppResult<SeparationSession> {
    state.sidecar.ensure_started().await?;
    let url = format!("{}/separate", state.sidecar.http_base());
    let body = serde_json::json!({
        "input_path": payload.input_path,
        "model": payload.model.unwrap_or_else(|| "htdemucs".into()),
        "two_stems": payload.two_stems.unwrap_or(true),
    });
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let resp = client
        .post(&url)
        .json(&body)
        .send()
        .await
        .map_err(AppError::Http)?;
    if !resp.status().is_success() {
        let txt = resp.text().await.unwrap_or_default();
        return Err(AppError::Internal(format!("sidecar /separate 失败: {txt}")));
    }
    let session: SeparationSession = resp.json().await.map_err(AppError::Http)?;
    Ok(session)
}

#[tauri::command]
pub async fn get_separation_status(
    state: State<'_, AppState>,
    session_id: String,
) -> AppResult<SeparationStatus> {
    if !state.sidecar.is_running() {
        return Err(AppError::SidecarNotRunning);
    }
    let url = format!(
        "{}/separate/status/{}",
        state.sidecar.http_base(),
        session_id
    );
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let resp = client.get(&url).send().await.map_err(AppError::Http)?;
    if !resp.status().is_success() {
        return Err(AppError::Internal(format!(
            "查询分离状态失败: {}",
            resp.status()
        )));
    }
    let st: SeparationStatus = resp.json().await.map_err(AppError::Http)?;
    Ok(st)
}

#[tauri::command]
pub async fn cancel_separation(state: State<'_, AppState>, session_id: String) -> AppResult<()> {
    if !state.sidecar.is_running() {
        return Ok(());
    }
    let url = format!(
        "{}/separate/cancel/{}",
        state.sidecar.http_base(),
        session_id
    );
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let _ = client.post(&url).send().await.map_err(AppError::Http)?;
    Ok(())
}
