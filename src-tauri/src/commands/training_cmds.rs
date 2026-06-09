//! 本机模型训练命令。
//!
//! 训练任务委托给 Python sidecar（HTTP API：/train）。
//! 前端负责启动、轮询状态和取消；sidecar 负责 GPU/训练脚本检测。

use crate::error::{AppError, AppResult};
use crate::state::AppState;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::State;

#[derive(Debug, Deserialize)]
pub struct StartTrainingPayload {
    pub dataset_dir: String,
    pub voice_name: String,
    pub training_package_dir: Option<String>,
    pub epochs: Option<u32>,
    pub batch_size: Option<u32>,
    pub sample_rate: Option<u32>,
    pub f0_method: Option<String>,
    pub save_every_epoch: Option<u32>,
    pub model_version: Option<String>,
    pub gpu_ids: Option<String>,
    pub cache_gpu: Option<bool>,
    pub save_latest_only: Option<bool>,
    pub save_every_weights: Option<bool>,
    pub pretrained_g: Option<String>,
    pub pretrained_d: Option<String>,
    pub use_gpu: Option<bool>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TrainingSession {
    pub session_id: String,
}

#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct TrainingStatus {
    pub session_id: String,
    pub state: String,
    pub progress: f32,
    pub message: Option<String>,
    pub error: Option<String>,
    pub pth_path: Option<String>,
    pub index_path: Option<String>,
    pub log_path: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct TrainingGpuInfo {
    pub available: bool,
    pub backend: String,
    pub name: String,
}

const HTTP_TIMEOUT: Duration = Duration::from_secs(8);

#[tauri::command]
pub async fn get_training_gpu(state: State<'_, AppState>) -> AppResult<TrainingGpuInfo> {
    state.sidecar.ensure_started().await?;
    let url = format!("{}/train/gpu", state.sidecar.http_base());
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let resp = client.get(&url).send().await.map_err(AppError::Http)?;
    if !resp.status().is_success() {
        return Err(AppError::Internal(format!(
            "查询训练 GPU 失败: {}",
            resp.status()
        )));
    }
    let info: TrainingGpuInfo = resp.json().await.map_err(AppError::Http)?;
    Ok(info)
}

#[tauri::command]
pub async fn start_training(
    state: State<'_, AppState>,
    payload: StartTrainingPayload,
) -> AppResult<TrainingSession> {
    state.sidecar.ensure_started().await?;
    let url = format!("{}/train", state.sidecar.http_base());
    let body = serde_json::json!({
        "dataset_dir": payload.dataset_dir,
        "voice_name": payload.voice_name,
        "training_package_dir": payload.training_package_dir,
        "epochs": payload.epochs.unwrap_or(200),
        "batch_size": payload.batch_size.unwrap_or(4),
        "sample_rate": payload.sample_rate.unwrap_or(40_000),
        "f0_method": payload.f0_method.unwrap_or_else(|| "rmvpe".into()),
        "save_every_epoch": payload.save_every_epoch.unwrap_or(10),
        "model_version": payload.model_version.unwrap_or_else(|| "v2".into()),
        "gpu_ids": payload.gpu_ids,
        "cache_gpu": payload.cache_gpu.unwrap_or(false),
        "save_latest_only": payload.save_latest_only.unwrap_or(true),
        "save_every_weights": payload.save_every_weights.unwrap_or(false),
        "pretrained_g": payload.pretrained_g,
        "pretrained_d": payload.pretrained_d,
        "use_gpu": payload.use_gpu.unwrap_or(true),
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
        return Err(AppError::Internal(format!("sidecar /train 失败: {txt}")));
    }
    let session: TrainingSession = resp.json().await.map_err(AppError::Http)?;
    Ok(session)
}

#[tauri::command]
pub async fn get_training_status(
    state: State<'_, AppState>,
    session_id: String,
) -> AppResult<TrainingStatus> {
    if !state.sidecar.is_running() {
        return Err(AppError::SidecarNotRunning);
    }
    let url = format!("{}/train/status/{}", state.sidecar.http_base(), session_id);
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let resp = client.get(&url).send().await.map_err(AppError::Http)?;
    if !resp.status().is_success() {
        return Err(AppError::Internal(format!(
            "查询训练状态失败: {}",
            resp.status()
        )));
    }
    let st: TrainingStatus = resp.json().await.map_err(AppError::Http)?;
    Ok(st)
}

#[tauri::command]
pub async fn cancel_training(state: State<'_, AppState>, session_id: String) -> AppResult<()> {
    if !state.sidecar.is_running() {
        return Ok(());
    }
    let url = format!("{}/train/cancel/{}", state.sidecar.http_base(), session_id);
    let client = reqwest::Client::builder()
        .timeout(HTTP_TIMEOUT)
        .build()
        .map_err(|e| AppError::Internal(e.to_string()))?;
    let _ = client.post(&url).send().await.map_err(AppError::Http)?;
    Ok(())
}
