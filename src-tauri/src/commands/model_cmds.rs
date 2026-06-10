//! 模型管理命令：列表、导入、下载预设。

use crate::error::{AppError, AppResult};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct VoiceModelInfo {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub category: String,
    pub gender: String,
    pub sample_rate: u32,
    pub pth_path: Option<String>,
    pub index_path: Option<String>,
    pub installed: bool,
    pub recommended_pitch: i32,
    pub source_url: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
struct Manifest {
    voices: Vec<VoiceModelInfo>,
}

fn models_dir() -> AppResult<PathBuf> {
    let base = dirs::data_local_dir()
        .or_else(dirs::data_dir)
        .ok_or_else(|| AppError::Internal("无法解析本地数据目录".into()))?;
    let dir = base.join("rvc-voice-changer").join("models");
    std::fs::create_dir_all(&dir)?;
    Ok(dir)
}

fn rmvpe_path() -> AppResult<PathBuf> {
    Ok(models_dir()?.join("rmvpe").join("rmvpe.pt"))
}

fn hubert_path() -> AppResult<PathBuf> {
    Ok(models_dir()?.join("hubert").join("hubert_base.pt"))
}

fn manifest_path() -> AppResult<PathBuf> {
    Ok(models_dir()?.join("manifest.json"))
}

fn load_manifest() -> AppResult<Manifest> {
    let path = manifest_path()?;
    if !path.exists() {
        let m = default_manifest();
        std::fs::write(&path, serde_json::to_vec_pretty(&m)?)?;
        return Ok(m);
    }
    let bytes = std::fs::read(&path)?;
    let m: Manifest = serde_json::from_slice(&bytes)?;
    Ok(m)
}

fn save_manifest(m: &Manifest) -> AppResult<()> {
    let path = manifest_path()?;
    std::fs::write(path, serde_json::to_vec_pretty(m)?)?;
    Ok(())
}

#[tauri::command]
pub fn list_voice_models() -> AppResult<Vec<VoiceModelInfo>> {
    let m = load_manifest()?;
    let dir = models_dir()?;
    let voices = m
        .voices
        .into_iter()
        .map(|mut v| {
            let pth = dir.join("voices").join(&v.id).join(format!("{}.pth", v.id));
            v.installed = pth.exists();
            v.pth_path = if pth.exists() {
                Some(pth.to_string_lossy().into_owned())
            } else {
                None
            };
            let idx = dir
                .join("voices")
                .join(&v.id)
                .join(format!("{}.index", v.id));
            v.index_path = if idx.exists() {
                Some(idx.to_string_lossy().into_owned())
            } else {
                None
            };
            v
        })
        .collect();
    Ok(voices)
}

#[derive(Debug, Deserialize)]
pub struct ImportPayload {
    pub voice_id: String,
    pub pth_path: String,
    pub index_path: Option<String>,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub category: Option<String>,
    pub gender: Option<String>,
    pub sample_rate: Option<u32>,
    pub recommended_pitch: Option<i32>,
}

#[tauri::command]
pub fn import_voice_model(payload: ImportPayload) -> AppResult<VoiceModelInfo> {
    let dir = models_dir()?.join("voices").join(&payload.voice_id);
    std::fs::create_dir_all(&dir)?;

    let pth_dst = dir.join(format!("{}.pth", payload.voice_id));
    std::fs::copy(&payload.pth_path, &pth_dst)?;
    if let Some(idx) = payload.index_path.as_ref() {
        let idx_dst = dir.join(format!("{}.index", payload.voice_id));
        std::fs::copy(idx, idx_dst)?;
    }

    let mut m = load_manifest()?;
    let index_dst = dir.join(format!("{}.index", payload.voice_id));
    let next_info = match m.voices.iter_mut().find(|v| v.id == payload.voice_id) {
        Some(info) => {
            if let Some(display_name) = payload.display_name.as_ref() {
                info.display_name = display_name.trim().to_string();
            }
            if let Some(description) = payload.description.as_ref() {
                info.description = description.trim().to_string();
            }
            if let Some(category) = payload.category.as_ref() {
                info.category = category.trim().to_string();
            }
            if let Some(gender) = payload.gender.as_ref() {
                info.gender = gender.trim().to_string();
            }
            if let Some(sample_rate) = payload.sample_rate {
                info.sample_rate = sample_rate;
            }
            if let Some(recommended_pitch) = payload.recommended_pitch {
                info.recommended_pitch = recommended_pitch;
            }
            info.pth_path = Some(pth_dst.to_string_lossy().into_owned());
            info.index_path = index_dst
                .exists()
                .then(|| index_dst.to_string_lossy().into_owned());
            info.installed = true;
            info.clone()
        }
        None => {
            let info = VoiceModelInfo {
                id: payload.voice_id.clone(),
                display_name: payload
                    .display_name
                    .as_deref()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .unwrap_or(&payload.voice_id)
                    .to_string(),
                description: payload
                    .description
                    .as_deref()
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .unwrap_or("用户导入的自定义音色")
                    .to_string(),
                category: payload.category.unwrap_or_else(|| "custom".into()),
                gender: payload.gender.unwrap_or_else(|| "unknown".into()),
                sample_rate: payload.sample_rate.unwrap_or(40_000),
                pth_path: Some(pth_dst.to_string_lossy().into_owned()),
                index_path: index_dst
                    .exists()
                    .then(|| index_dst.to_string_lossy().into_owned()),
                installed: true,
                recommended_pitch: payload.recommended_pitch.unwrap_or(0),
                source_url: None,
            };
            m.voices.push(info.clone());
            info
        }
    };
    save_manifest(&m)?;
    Ok(next_info)
}

#[derive(Debug, Deserialize)]
pub struct ImportTrainingOutputPayload {
    pub pth_path: String,
    pub index_path: Option<String>,
    pub voice_name: String,
    pub sample_rate: Option<u32>,
    pub model_version: Option<String>,
}

#[tauri::command]
pub fn import_training_output(payload: ImportTrainingOutputPayload) -> AppResult<VoiceModelInfo> {
    let voice_id = unique_voice_id(&sanitize_voice_id(&payload.voice_name))?;
    import_voice_model(ImportPayload {
        voice_id,
        pth_path: payload.pth_path,
        index_path: payload.index_path,
        display_name: Some(payload.voice_name),
        description: Some(format!(
            "本机训练生成的 RVC {} 音色",
            payload.model_version.unwrap_or_else(|| "v2".into())
        )),
        category: Some("custom".into()),
        gender: Some("unknown".into()),
        sample_rate: payload.sample_rate,
        recommended_pitch: Some(0),
    })
}

#[derive(Debug, Deserialize)]
pub struct DownloadPayload {
    pub voice_id: String,
}

#[tauri::command]
pub async fn download_preset_model(payload: DownloadPayload) -> AppResult<VoiceModelInfo> {
    let m = load_manifest()?;
    let info = m
        .voices
        .iter()
        .find(|v| v.id == payload.voice_id)
        .cloned()
        .ok_or_else(|| AppError::ModelNotFound(payload.voice_id.clone()))?;

    let url = info
        .source_url
        .clone()
        .ok_or_else(|| AppError::ModelNotFound(format!("{} 没有下载链接", payload.voice_id)))?;

    let dir = models_dir()?.join("voices").join(&payload.voice_id);
    std::fs::create_dir_all(&dir)?;
    let dst = dir.join(format!("{}.pth", payload.voice_id));

    tracing::info!("下载模型 {} <- {}", payload.voice_id, url);
    let resp = reqwest::get(&url).await?;
    let bytes = resp.bytes().await?;
    std::fs::write(&dst, &bytes)?;

    Ok(info)
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct F0ModelStatus {
    pub rmvpe_installed: bool,
    pub rmvpe_path: Option<String>,
    pub rmvpe_download_url: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BaseModelStatus {
    pub hubert_installed: bool,
    pub hubert_path: Option<String>,
    pub hubert_download_url: String,
    pub rmvpe_installed: bool,
    pub rmvpe_path: Option<String>,
    pub rmvpe_download_url: String,
    pub installed_voice_count: usize,
    pub total_voice_count: usize,
    pub models_dir: String,
    pub pretrained_weights: Vec<PretrainedWeightInfo>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PretrainedWeightInfo {
    pub id: String,
    pub kind: String,
    pub version: String,
    pub sample_rate: u32,
    pub file_name: String,
    pub url: String,
}

#[tauri::command]
pub fn get_f0_model_status() -> AppResult<F0ModelStatus> {
    let path = rmvpe_path()?;
    Ok(F0ModelStatus {
        rmvpe_installed: path.exists(),
        rmvpe_path: path.exists().then(|| path.to_string_lossy().into_owned()),
        rmvpe_download_url: "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt"
            .into(),
    })
}

#[tauri::command]
pub fn get_base_model_status() -> AppResult<BaseModelStatus> {
    let hubert = hubert_path()?;
    let rmvpe = rmvpe_path()?;
    let voices = list_voice_models()?;
    let models = models_dir()?;
    Ok(BaseModelStatus {
        hubert_installed: hubert.exists(),
        hubert_path: hubert.exists().then(|| hubert.to_string_lossy().into_owned()),
        hubert_download_url:
            "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/hubert_base.pt"
                .into(),
        rmvpe_installed: rmvpe.exists(),
        rmvpe_path: rmvpe.exists().then(|| rmvpe.to_string_lossy().into_owned()),
        rmvpe_download_url:
            "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/rmvpe.pt".into(),
        installed_voice_count: voices.iter().filter(|v| v.installed).count(),
        total_voice_count: voices.len(),
        models_dir: models.to_string_lossy().into_owned(),
        pretrained_weights: pretrained_weight_catalog(),
    })
}

#[derive(Debug, Deserialize)]
pub struct ImportF0ModelPayload {
    pub kind: String,
    pub path: String,
}

#[tauri::command]
pub fn import_f0_model(payload: ImportF0ModelPayload) -> AppResult<F0ModelStatus> {
    if payload.kind != "rmvpe" {
        return Err(AppError::Internal(format!(
            "暂不支持的 F0 模型类型: {}",
            payload.kind
        )));
    }
    let src = Path::new(&payload.path);
    if !src.exists() {
        return Err(AppError::Internal(format!(
            "F0 模型文件不存在: {}",
            payload.path
        )));
    }
    let dst = rmvpe_path()?;
    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::copy(src, &dst)?;
    get_f0_model_status()
}

#[derive(Debug, Deserialize)]
pub struct ImportBaseModelPayload {
    pub kind: String,
    pub path: String,
}

#[tauri::command]
pub fn import_base_model(payload: ImportBaseModelPayload) -> AppResult<BaseModelStatus> {
    let src = Path::new(&payload.path);
    if !src.exists() {
        return Err(AppError::Internal(format!(
            "基础模型文件不存在: {}",
            payload.path
        )));
    }
    let dst = match payload.kind.as_str() {
        "hubert" | "contentvec" => hubert_path()?,
        "rmvpe" => rmvpe_path()?,
        other => {
            return Err(AppError::Internal(format!(
                "暂不支持的基础模型类型: {other}"
            )));
        }
    };
    if let Some(parent) = dst.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::copy(src, dst)?;
    get_base_model_status()
}

fn sanitize_voice_id(name: &str) -> String {
    let safe: String = name
        .trim()
        .chars()
        .map(|ch| {
            if ch.is_alphanumeric() || ch == '-' || ch == '_' {
                ch.to_lowercase().next().unwrap_or(ch)
            } else if ch.is_whitespace() {
                '_'
            } else {
                '_'
            }
        })
        .collect();
    let compact = safe
        .split('_')
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join("_");
    if compact.is_empty() {
        "trained_voice".into()
    } else {
        compact
    }
}

fn unique_voice_id(base: &str) -> AppResult<String> {
    let manifest = load_manifest()?;
    let voices_dir = models_dir()?.join("voices");
    for idx in 0..10_000 {
        let candidate = if idx == 0 {
            base.to_string()
        } else {
            format!("{base}_{idx}")
        };
        let exists_in_manifest = manifest.voices.iter().any(|v| v.id == candidate);
        let exists_on_disk = voices_dir.join(&candidate).exists();
        if !exists_in_manifest && !exists_on_disk {
            return Ok(candidate);
        }
    }
    Err(AppError::Internal(format!(
        "无法为训练产物生成唯一音色 ID: {base}"
    )))
}

fn pretrained_weight_catalog() -> Vec<PretrainedWeightInfo> {
    let mut out = Vec::new();
    let base = "https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main";
    for version in ["v2", "v1"] {
        for sample_rate in [32_000_u32, 40_000, 48_000] {
            let sr = sample_rate / 1000;
            for kind in ["G", "D"] {
                let file_name = format!("f0{kind}{sr}k.pth");
                let dir = if version == "v2" {
                    "pretrained_v2"
                } else {
                    "pretrained"
                };
                out.push(PretrainedWeightInfo {
                    id: format!("{version}-{kind}-{sample_rate}"),
                    kind: kind.into(),
                    version: version.into(),
                    sample_rate,
                    file_name: file_name.clone(),
                    url: format!("{base}/{dir}/{file_name}"),
                });
            }
        }
    }
    out
}

/// 5 个预设音色的初始 manifest。`source_url` 留空，第一版用「用户手动导入」。
/// 因为 RVC 模型版权状况复杂（妙音工坊很多付费、HuggingFace 部分需登录），
/// 我们不预置直链，而是引导用户去 docs/MODELS.md 自己下。
fn default_manifest() -> Manifest {
    Manifest {
        voices: vec![
            VoiceModelInfo {
                id: "yujie".into(),
                display_name: "御姐音".into(),
                description: "成熟知性、略带磁性的女声，适合冷静向直播".into(),
                category: "female".into(),
                gender: "female".into(),
                sample_rate: 48_000,
                pth_path: None,
                index_path: None,
                installed: false,
                recommended_pitch: 0,
                source_url: None,
            },
            VoiceModelInfo {
                id: "loli".into(),
                display_name: "萝莉音".into(),
                description: "娇小可爱的少女声，适合 ACG / 卖萌向直播".into(),
                category: "female".into(),
                gender: "female".into(),
                sample_rate: 40_000,
                pth_path: None,
                index_path: None,
                installed: false,
                recommended_pitch: 12,
                source_url: None,
            },
            VoiceModelInfo {
                id: "shaonian".into(),
                display_name: "小男孩 (正气少年)".into(),
                description: "热血少年音，清脆有力、一身正气".into(),
                category: "male".into(),
                gender: "male".into(),
                sample_rate: 44_100,
                pth_path: None,
                index_path: None,
                installed: false,
                recommended_pitch: 6,
                source_url: None,
            },
            VoiceModelInfo {
                id: "naiqing".into(),
                display_name: "奶青音".into(),
                description: "甜美中带点冷感的年轻女声（社区俗称\"奶青\"）".into(),
                category: "female".into(),
                gender: "female".into(),
                sample_rate: 44_100,
                pth_path: None,
                index_path: None,
                installed: false,
                recommended_pitch: 2,
                source_url: None,
            },
            VoiceModelInfo {
                id: "qingshu".into(),
                display_name: "青叔音".into(),
                description: "30~40 岁成熟磁性男声，沉稳有质感".into(),
                category: "male".into(),
                gender: "male".into(),
                sample_rate: 48_000,
                pth_path: None,
                index_path: None,
                installed: false,
                recommended_pitch: 0,
                source_url: None,
            },
        ],
    }
}
