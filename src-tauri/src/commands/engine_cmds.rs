//! 引擎控制命令：start / stop / 切换音色 / 调音高。

use crate::audio::engine::{EngineStatus, StartConfig};
use crate::error::AppResult;
use crate::state::AppState;
use serde::{Deserialize, Serialize};
use tauri::State;

#[derive(Debug, Deserialize)]
pub struct StartEnginePayload {
    pub input_device: Option<String>,
    pub output_device: Option<String>,
    pub voice_id: String,
    pub pitch_shift: Option<i32>,
}

#[derive(Debug, Serialize)]
pub struct EngineStatusPayload {
    pub status: EngineStatus,
    pub current_voice: Option<String>,
    pub pitch_shift: i32,
}

#[tauri::command]
pub async fn start_engine(
    state: State<'_, AppState>,
    payload: StartEnginePayload,
) -> AppResult<()> {
    state.sidecar.ensure_started().await?;

    let cfg = StartConfig {
        input_device: payload.input_device,
        output_device: payload.output_device,
        voice_id: payload.voice_id.clone(),
        pitch_shift: payload.pitch_shift.unwrap_or(0),
        sidecar_ws_url: state.sidecar.ws_url(),
        chunk_size: 1024,
        latency_secs: 0.5,
    };

    {
        let mut v = state.current_voice.write();
        *v = Some(payload.voice_id);
    }
    {
        let mut p = state.pitch_shift.write();
        *p = cfg.pitch_shift;
    }

    let engine = state.audio_engine.clone();
    let dsp = state.dsp.clone();
    let mut g = engine.lock().await;
    g.start(cfg, dsp).await?;
    Ok(())
}

#[tauri::command]
pub async fn stop_engine(state: State<'_, AppState>) -> AppResult<()> {
    let engine = state.audio_engine.clone();
    let mut g = engine.lock().await;
    g.stop().await
}

#[tauri::command]
pub async fn get_engine_status(
    state: State<'_, AppState>,
) -> AppResult<EngineStatusPayload> {
    let engine = state.audio_engine.lock().await;
    Ok(EngineStatusPayload {
        status: engine.status(),
        current_voice: state.current_voice.read().clone(),
        pitch_shift: *state.pitch_shift.read(),
    })
}

#[tauri::command]
pub async fn set_voice(state: State<'_, AppState>, voice_id: String) -> AppResult<()> {
    {
        let mut v = state.current_voice.write();
        *v = Some(voice_id.clone());
    }
    // TODO: 通过 sidecar IPC 在不重启引擎的情况下热切换音色
    tracing::info!("set_voice -> {voice_id}");
    Ok(())
}

#[tauri::command]
pub async fn set_pitch_shift(state: State<'_, AppState>, semitones: i32) -> AppResult<()> {
    let semitones = semitones.clamp(-24, 24);
    let mut p = state.pitch_shift.write();
    *p = semitones;
    tracing::info!("set_pitch_shift -> {semitones}");
    Ok(())
}
