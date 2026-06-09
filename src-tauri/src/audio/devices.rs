//! 音频设备枚举与虚拟声卡识别。
//!
//! Windows 上 VB-Cable 安装后会出现：
//! - 输入端：`CABLE Output (VB-Audio Virtual Cable)`
//! - 输出端：`CABLE Input (VB-Audio Virtual Cable)`
//!
//! 我们关心的是把变声后的音频送到 `CABLE Input`（作为输出设备），
//! 这样直播软件 / StudioOne 监听 `CABLE Output`（作为输入设备）即可拿到音频。
//!
//! macOS 等价物为 BlackHole：
//! - `BlackHole 2ch` 既是输入也是输出（虚拟回环）

use crate::error::{AppError, AppResult};
use cpal::traits::{DeviceTrait, HostTrait};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioDeviceInfo {
    pub name: String,
    pub is_default: bool,
    pub is_virtual_cable: bool,
    pub sample_rate: u32,
    pub channels: u16,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeviceKind {
    Input,
    Output,
}

const VIRTUAL_CABLE_KEYWORDS: &[&str] = &[
    "CABLE",       // VB-Cable
    "VB-Audio",    // VB-Audio
    "Virtual",     // 通用关键字
    "BlackHole",   // macOS BlackHole
    "Soundflower", // macOS Soundflower (legacy)
    "VoiceMeeter", // VoiceMeeter
];

pub fn is_virtual_cable_name(name: &str) -> bool {
    VIRTUAL_CABLE_KEYWORDS
        .iter()
        .any(|kw| name.to_ascii_lowercase().contains(&kw.to_ascii_lowercase()))
}

pub fn list_devices(kind: DeviceKind) -> AppResult<Vec<AudioDeviceInfo>> {
    let host = cpal::default_host();

    let default_name = match kind {
        DeviceKind::Input => host.default_input_device().and_then(|d| d.name().ok()),
        DeviceKind::Output => host.default_output_device().and_then(|d| d.name().ok()),
    };

    let devices_iter = match kind {
        DeviceKind::Input => host
            .input_devices()
            .map_err(|e| AppError::AudioDevice(e.to_string()))?,
        DeviceKind::Output => host
            .output_devices()
            .map_err(|e| AppError::AudioDevice(e.to_string()))?,
    };

    let mut result = Vec::new();
    for d in devices_iter {
        let name = match d.name() {
            Ok(n) => n,
            Err(_) => continue,
        };
        let cfg = match kind {
            DeviceKind::Input => d.default_input_config().ok(),
            DeviceKind::Output => d.default_output_config().ok(),
        };
        let (sr, ch) = match cfg {
            Some(c) => (c.sample_rate().0, c.channels()),
            None => (0, 0),
        };
        result.push(AudioDeviceInfo {
            is_default: default_name.as_deref() == Some(name.as_str()),
            is_virtual_cable: is_virtual_cable_name(&name),
            name,
            sample_rate: sr,
            channels: ch,
        });
    }
    Ok(result)
}

pub fn find_first_virtual_cable_output() -> AppResult<Option<AudioDeviceInfo>> {
    let list = list_devices(DeviceKind::Output)?;
    Ok(list.into_iter().find(|d| d.is_virtual_cable))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keyword_match() {
        assert!(is_virtual_cable_name(
            "CABLE Input (VB-Audio Virtual Cable)"
        ));
        assert!(is_virtual_cable_name("BlackHole 2ch"));
        assert!(!is_virtual_cable_name("Built-in Microphone"));
    }
}
