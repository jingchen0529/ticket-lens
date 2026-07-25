// Prevent additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, State};

/// 后端固定端口，需与前端 api.js 的 BACKEND_PORT 一致。
const BACKEND_PORT: u16 = 8756;

/// 持有后端子进程句柄，退出时杀掉，避免僵尸进程占端口。
struct Backend(Mutex<Option<Child>>);

/// 在打包环境里定位后端 exe（PyInstaller onedir，作为 Tauri resource 分发）。
///
/// 资源结构（打进包的 daxi/ 目录）：
///   daxi/daxi(.exe)          后端可执行文件
///   daxi/_internal/...       PyInstaller 依赖
///   daxi/ms-playwright/...   两个 Chromium（有头 + headless_shell）
///   daxi/configs/...         配置模板
fn backend_exe(app: &tauri::AppHandle) -> Option<std::path::PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let exe_name = if cfg!(windows) { "daxi.exe" } else { "daxi" };
    let candidate = resource_dir.join("daxi").join(exe_name);
    if candidate.exists() {
        Some(candidate)
    } else {
        None
    }
}

/// 启动后端。dev 模式（无打包资源）下跳过：开发时手动 `daxi serve`。
fn spawn_backend(app: &tauri::AppHandle) -> Option<Child> {
    let exe = match backend_exe(app) {
        Some(p) => p,
        None => {
            eprintln!(
                "[tauri] 未找到打包后端 exe，跳过自动启动（dev 模式请手动运行 daxi serve）"
            );
            return None;
        }
    };
    eprintln!("[tauri] launching backend: {}", exe.display());
    let mut cmd = Command::new(&exe);
    cmd.arg("serve")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(BACKEND_PORT.to_string());

    // Windows：后端 exe 是 console=True，直接拉起会弹 cmd 黑窗。
    // CREATE_NO_WINDOW (0x0800_0000) 抑制控制台窗口。
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    match cmd.spawn() {
        Ok(child) => Some(child),
        Err(e) => {
            eprintln!("[tauri] 启动后端失败: {e}");
            None
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            let child = spawn_backend(&handle);
            let state: State<Backend> = app.state();
            *state.0.lock().unwrap() = child;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // 应用退出：杀掉后端子进程。
            if let RunEvent::ExitRequested { .. } = event {
                let state: State<Backend> = app_handle.state();
                // 先取出子进程再释放锁，避免 MutexGuard 临时值跨越 if 块导致借用超期。
                let child = state.0.lock().unwrap().take();
                if let Some(mut child) = child {
                    let _ = child.kill();
                    eprintln!("[tauri] backend killed on exit");
                }
            }
        });
}
