//! 引擎控制命令：start / stop / 切换音色 / 调音高。

use crate::audio::engine::{EngineStatus, RealtimeConfig, StartConfig};
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
    pub realtime_config: Option<RealtimeConfig>,
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

    let realtime_config = payload.realtime_config.unwrap_or_default();
    let chunk_size = realtime_config.chunk_size.clamp(1024, 16_384);
    let latency_secs = (realtime_config.buffer_ms as f32 / 1000.0).clamp(0.1, 2.0);
    let cfg = StartConfig {
        input_device: payload.input_device,
        output_device: payload.output_device,
        voice_id: payload.voice_id.clone(),
        pitch_shift: payload.pitch_shift.unwrap_or(0),
        sidecar_ws_url: state.sidecar.ws_url(),
        chunk_size,
        latency_secs,
        realtime_config,
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
pub async fn get_engine_status(state: State<'_, AppState>) -> AppResult<EngineStatusPayload> {
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
    let engine = state.audio_engine.lock().await;
    engine.set_voice(voice_id.clone()).await?;
    tracing::info!("set_voice -> {voice_id}");
    Ok(())
}

#[tauri::command]
pub async fn set_pitch_shift(state: State<'_, AppState>, semitones: i32) -> AppResult<()> {
    let semitones = semitones.clamp(-24, 24);
    {
        let mut p = state.pitch_shift.write();
        *p = semitones;
    }
    let engine = state.audio_engine.lock().await;
    engine.set_pitch(semitones).await?;
    tracing::info!("set_pitch_shift -> {semitones}");
    Ok(())
}

#[tauri::command]
pub async fn set_realtime_config(
    state: State<'_, AppState>,
    config: RealtimeConfig,
) -> AppResult<()> {
    let engine = state.audio_engine.lock().await;
    engine.set_realtime_config(config).await?;
    Ok(())
}
