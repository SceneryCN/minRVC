//! RVC 实时变声器 - Tauri 后端入口
//!
//! 职责拆分：
//! - audio: 麦克风采集 + 虚拟声卡输出 + 环形缓冲
//! - ipc:   与 Python sidecar 通过 WebSocket 流式通信
//! - sidecar: Python 进程生命周期
//! - commands: 暴露给前端的 Tauri 命令
//! - state: 全局应用状态

mod audio;
mod commands;
mod error;
mod ipc;
mod sidecar;
mod state;

use commands::{
    audio_cmds, dsp_cmds, engine_cmds, model_cmds, separation_cmds, training_cmds,
};
use state::AppState;
use tracing_subscriber::{fmt, prelude::*, EnvFilter};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    init_logging();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AppState::new())
        .invoke_handler(tauri::generate_handler![
            audio_cmds::list_input_devices,
            audio_cmds::list_output_devices,
            audio_cmds::detect_virtual_cable,
            audio_cmds::get_audio_meter,
            engine_cmds::start_engine,
            engine_cmds::stop_engine,
            engine_cmds::get_engine_status,
            engine_cmds::set_voice,
            engine_cmds::set_pitch_shift,
            engine_cmds::set_realtime_config,
            model_cmds::list_voice_models,
            model_cmds::import_voice_model,
            model_cmds::import_training_output,
            model_cmds::download_preset_model,
            model_cmds::get_base_model_status,
            model_cmds::import_base_model,
            model_cmds::get_f0_model_status,
            model_cmds::import_f0_model,
            dsp_cmds::get_dsp_config,
            dsp_cmds::set_dsp_config,
            dsp_cmds::get_dsp_status,
            separation_cmds::start_separation,
            separation_cmds::get_separation_status,
            separation_cmds::cancel_separation,
            training_cmds::get_training_gpu,
            training_cmds::start_training,
            training_cmds::get_training_status,
            training_cmds::cancel_training,
        ])
        .setup(|app| {
            tracing::info!("声变 Tauri 应用启动");
            // sidecar 由前端按需启动，不在此处自动拉起
            let _ = app;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("运行 Tauri 应用失败");
}

fn init_logging() {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info,rvc_voice_changer_lib=debug"));
    tracing_subscriber::registry()
        .with(filter)
        .with(fmt::layer().with_target(true).with_thread_ids(false))
        .init();
}
