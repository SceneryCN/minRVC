//! 启停 Python sidecar 进程。
//!
//! 设计为「单例」：只允许同时存在一个 sidecar。
//! 端口固定 8765（可配置），健康检查通过 HTTP GET /health。

use crate::error::{AppError, AppResult};
use parking_lot::Mutex;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const SIDECAR_PORT: u16 = 8765;
const HEALTH_CHECK_TIMEOUT: Duration = Duration::from_millis(500);
const HEALTH_CHECK_RETRIES: u32 = 60; // 30s 总超时

pub struct SidecarManager {
    child: Mutex<Option<Child>>,
}

impl Default for SidecarManager {
    fn default() -> Self {
        Self::new()
    }
}

impl SidecarManager {
    pub fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    pub fn ws_url(&self) -> String {
        format!("ws://127.0.0.1:{}/stream", SIDECAR_PORT)
    }

    pub fn health_url(&self) -> String {
        format!("http://127.0.0.1:{}/health", SIDECAR_PORT)
    }

    pub fn http_base(&self) -> String {
        format!("http://127.0.0.1:{}", SIDECAR_PORT)
    }

    pub fn is_running(&self) -> bool {
        let mut g = self.child.lock();
        if let Some(child) = g.as_mut() {
            match child.try_wait() {
                Ok(Some(_)) => {
                    *g = None;
                    false
                }
                Ok(None) => true,
                Err(_) => true,
            }
        } else {
            false
        }
    }

    pub async fn ensure_started(&self) -> AppResult<()> {
        if self.is_running() && self.health_check().await.is_ok() {
            return Ok(());
        }
        self.spawn()?;
        self.wait_healthy().await
    }

    fn spawn(&self) -> AppResult<()> {
        let mut g = self.child.lock();
        if let Some(c) = g.as_mut() {
            let _ = c.kill();
        }

        // 优先尝试打包后的二进制（生产环境）
        let exe_path = locate_sidecar_binary();

        let mut cmd = if let Some(path) = exe_path {
            tracing::info!("使用打包的 sidecar: {:?}", path);
            Command::new(path)
        } else {
            tracing::warn!("未找到打包 sidecar，回退到开发模式 (python -m rvc_engine.server)");
            let mut c = Command::new(python_exe());
            c.arg("-m").arg("rvc_engine.server");
            // 设置 cwd 为项目根目录下的 sidecar/
            if let Some(root) = project_root() {
                c.current_dir(root.join("sidecar"));
            }
            c
        };

        cmd.arg("--port")
            .arg(SIDECAR_PORT.to_string())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit());

        let child = cmd
            .spawn()
            .map_err(|e| AppError::SidecarStart(format!("spawn 失败: {e}")))?;
        *g = Some(child);
        Ok(())
    }

    async fn wait_healthy(&self) -> AppResult<()> {
        for i in 0..HEALTH_CHECK_RETRIES {
            tokio::time::sleep(Duration::from_millis(500)).await;
            if self.health_check().await.is_ok() {
                tracing::info!("sidecar 就绪 (耗时 {}ms)", (i + 1) * 500);
                return Ok(());
            }
        }
        Err(AppError::SidecarStart("sidecar 启动超时".into()))
    }

    async fn health_check(&self) -> AppResult<()> {
        let client = reqwest::Client::builder()
            .timeout(HEALTH_CHECK_TIMEOUT)
            .build()
            .map_err(|e| AppError::SidecarStart(e.to_string()))?;
        let resp = client
            .get(self.health_url())
            .send()
            .await
            .map_err(|e| AppError::SidecarStart(format!("health check: {e}")))?;
        if resp.status().is_success() {
            Ok(())
        } else {
            Err(AppError::SidecarStart(format!(
                "health status: {}",
                resp.status()
            )))
        }
    }

    pub fn stop(&self) {
        let mut g = self.child.lock();
        if let Some(mut c) = g.take() {
            let _ = c.kill();
            let _ = c.wait();
        }
    }
}

impl Drop for SidecarManager {
    fn drop(&mut self) {
        self.stop();
    }
}

fn python_exe() -> &'static str {
    if cfg!(target_os = "windows") {
        "python"
    } else {
        "python3"
    }
}

fn project_root() -> Option<std::path::PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let mut p = cwd.as_path();
    loop {
        if p.join("package.json").exists() && p.join("sidecar").exists() {
            return Some(p.to_path_buf());
        }
        match p.parent() {
            Some(parent) => p = parent,
            None => return None,
        }
    }
}

fn locate_sidecar_binary() -> Option<std::path::PathBuf> {
    let exe_dir = std::env::current_exe().ok()?.parent()?.to_path_buf();

    // Tauri externalBin 打包后文件名带 target triple，例如 rvc-sidecar-aarch64-apple-darwin
    if let Some(name) = sidecar_binary_name() {
        let p = exe_dir.join(name);
        if p.is_file() {
            return Some(p);
        }
    }

    // 兼容旧命名 / 开发产物
    let legacy = if cfg!(target_os = "windows") {
        ["rvc-sidecar.exe", "binaries/rvc-sidecar.exe"]
    } else {
        ["rvc-sidecar", "binaries/rvc-sidecar"]
    };
    for name in legacy {
        let p = exe_dir.join(name);
        if p.is_file() {
            return Some(p);
        }
    }

    // 兜底：扫描应用目录下任意 rvc-sidecar* 可执行文件
    if let Ok(entries) = std::fs::read_dir(&exe_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if !path.is_file() {
                continue;
            }
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with("rvc-sidecar") {
                return Some(path);
            }
        }
    }

    None
}

/// 与 `sidecar/build_sidecar.py` + Tauri `externalBin: binaries/rvc-sidecar` 命名一致。
fn sidecar_binary_name() -> Option<&'static str> {
    Some(match () {
        #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
        () => "rvc-sidecar-x86_64-pc-windows-msvc.exe",
        #[cfg(all(target_os = "macos", target_arch = "aarch64"))]
        () => "rvc-sidecar-aarch64-apple-darwin",
        #[cfg(all(target_os = "macos", target_arch = "x86_64"))]
        () => "rvc-sidecar-x86_64-apple-darwin",
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        () => "rvc-sidecar-x86_64-unknown-linux-gnu",
        #[cfg(all(target_os = "linux", target_arch = "aarch64"))]
        () => "rvc-sidecar-aarch64-unknown-linux-gnu",
        #[cfg(not(any(
            all(target_os = "windows", target_arch = "x86_64"),
            all(target_os = "macos", target_arch = "aarch64"),
            all(target_os = "macos", target_arch = "x86_64"),
            all(target_os = "linux", target_arch = "x86_64"),
            all(target_os = "linux", target_arch = "aarch64"),
        )))]
        () => return None,
    })
}
