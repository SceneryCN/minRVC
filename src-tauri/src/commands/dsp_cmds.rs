//! DSP（降噪 + VAD）相关命令。
//!
//! 前端通过这些命令调整运行时参数与读取实时状态。

use crate::audio::dsp::{DspConfig, DspStatus};
use crate::error::AppResult;
use crate::state::AppState;
use tauri::State;

#[tauri::command]
pub fn get_dsp_config(state: State<'_, AppState>) -> AppResult<DspConfig> {
    Ok(state.dsp.config())
}

#[tauri::command]
pub fn set_dsp_config(state: State<'_, AppState>, config: DspConfig) -> AppResult<()> {
    let cfg = sanitize(config);
    state.dsp.set_config(cfg);
    tracing::info!(
        "DSP 配置更新 denoise={}@{:.2} vad={}@{:.2}",
        cfg.denoise_enabled,
        cfg.denoise_strength,
        cfg.vad_enabled,
        cfg.vad_threshold
    );
    Ok(())
}

#[tauri::command]
pub fn get_dsp_status(state: State<'_, AppState>) -> AppResult<DspStatus> {
    Ok(state.dsp.status())
}

fn sanitize(mut cfg: DspConfig) -> DspConfig {
    cfg.denoise_strength = cfg.denoise_strength.clamp(0.0, 1.0);
    cfg.vad_threshold = cfg.vad_threshold.clamp(0.0, 1.0);
    cfg.vad_min_speech_ms = cfg.vad_min_speech_ms.clamp(50, 2000);
    cfg.vad_min_silence_ms = cfg.vad_min_silence_ms.clamp(50, 2000);
    cfg
}
