//! 音频设备相关命令：枚举、检测虚拟声卡、读取实时电平。

use crate::audio::devices::{
    find_first_virtual_cable_output, list_devices, AudioDeviceInfo, DeviceKind,
};
use crate::error::AppResult;
use crate::state::AppState;
use serde::Serialize;
use tauri::State;

#[derive(Debug, Serialize)]
pub struct AudioMeter {
    pub input_level: f32,
    pub output_level: f32,
}

#[tauri::command]
pub fn list_input_devices() -> AppResult<Vec<AudioDeviceInfo>> {
    list_devices(DeviceKind::Input)
}

#[tauri::command]
pub fn list_output_devices() -> AppResult<Vec<AudioDeviceInfo>> {
    list_devices(DeviceKind::Output)
}

#[tauri::command]
pub fn detect_virtual_cable() -> AppResult<Option<AudioDeviceInfo>> {
    find_first_virtual_cable_output()
}

#[tauri::command]
pub async fn get_audio_meter(state: State<'_, AppState>) -> AppResult<AudioMeter> {
    let engine = state.audio_engine.lock().await;
    Ok(AudioMeter {
        input_level: engine.capture_level(),
        output_level: engine.output_level(),
    })
}
