// Prevent additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Deserialize;
#[cfg(not(debug_assertions))]
use sysinfo::{Pid, Signal, System};
use tauri::{AppHandle, Manager, RunEvent, State};

/// 后端固定端口，需与前端 api.js 的 BACKEND_PORT 一致。
const BACKEND_PORT: u16 = 8756;
const BACKEND_SERVICE_ID: &str = "com.daxi.backend";
const BACKEND_API_PROTOCOL: u32 = 2;
const BACKEND_START_TIMEOUT: Duration = Duration::from_secs(20);
const BACKEND_STOP_TIMEOUT: Duration = Duration::from_secs(5);

/// 持有后端子进程句柄，退出时杀掉，避免僵尸进程占端口。
struct Backend(Mutex<Option<Child>>);

fn port_is_listening() -> bool {
    let address = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, BACKEND_PORT));
    TcpStream::connect_timeout(&address, Duration::from_millis(150)).is_ok()
}

#[cfg(any(not(debug_assertions), test))]
fn has_option(command: &[String], name: &str, value: &str) -> bool {
    command
        .windows(2)
        .any(|pair| pair[0] == name && pair[1] == value)
        || command
            .iter()
            .any(|argument| argument == &format!("{name}={value}"))
}

/// 只识别桌面壳历史版本启动的固定后端，绝不因 8756 被占用就误杀其他程序。
#[cfg(any(not(debug_assertions), test))]
fn is_daxi_backend_command(process_name: &str, command: &[String]) -> bool {
    let name = process_name.to_ascii_lowercase();
    let executable_matches = name == "daxi" || name == "daxi.exe";
    let serves_api = command
        .iter()
        .any(|argument| argument.eq_ignore_ascii_case("serve"));
    executable_matches
        && serves_api
        && has_option(command, "--host", "127.0.0.1")
        && has_option(command, "--port", &BACKEND_PORT.to_string())
}

#[cfg(not(debug_assertions))]
fn reclaim_stale_backends() {
    let mut system = System::new_all();
    let stale: Vec<Pid> = system
        .processes()
        .iter()
        .filter_map(|(pid, process)| {
            if pid.as_u32() != std::process::id()
                && is_daxi_backend_command(process.name(), process.cmd())
            {
                Some(*pid)
            } else {
                None
            }
        })
        .collect();

    for pid in &stale {
        if let Some(process) = system.process(*pid) {
            eprintln!("[tauri] stopping stale backend pid={}", pid.as_u32());
            // Unix 先 TERM 让 Uvicorn 有机会收尾；Windows 不支持该 signal，
            // 会在下面等待后使用 kill()/TerminateProcess 兜底。
            let _ = process.kill_with(Signal::Term);
        }
    }

    let deadline = Instant::now() + Duration::from_secs(2);
    while Instant::now() < deadline {
        system.refresh_processes();
        if stale.iter().all(|pid| system.process(*pid).is_none()) {
            return;
        }
        thread::sleep(Duration::from_millis(100));
    }

    system.refresh_processes();
    for pid in &stale {
        if let Some(process) = system.process(*pid) {
            eprintln!("[tauri] force killing stale backend pid={}", pid.as_u32());
            let _ = process.kill();
        }
    }
}

fn prepare_backend_port() -> Result<(), String> {
    #[cfg(not(debug_assertions))]
    reclaim_stale_backends();

    let deadline = Instant::now() + Duration::from_secs(4);
    while port_is_listening() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(100));
    }
    if port_is_listening() {
        Err(format!(
            "端口 {BACKEND_PORT} 仍被其他进程占用，拒绝连接旧后端"
        ))
    } else {
        Ok(())
    }
}

fn new_instance_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{}-{nanos}", std::process::id())
}

#[derive(Debug, Deserialize)]
struct BackendIdentity {
    service_id: String,
    api_protocol: u32,
    backend_version: String,
    pid: u32,
    parent_pid: Option<u32>,
    instance_id: String,
}

fn backend_identity_matches(
    identity: &BackendIdentity,
    expected_pid: u32,
    expected_parent_pid: u32,
    expected_instance_id: &str,
    expected_version: &str,
) -> bool {
    identity.service_id == BACKEND_SERVICE_ID
        && identity.api_protocol == BACKEND_API_PROTOCOL
        && identity.backend_version == expected_version
        && identity.pid == expected_pid
        && identity.parent_pid == Some(expected_parent_pid)
        && identity.instance_id == expected_instance_id
}

fn fetch_backend_identity() -> Option<BackendIdentity> {
    let address = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, BACKEND_PORT));
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(250)).ok()?;
    stream
        .set_read_timeout(Some(Duration::from_millis(500)))
        .ok()?;
    stream
        .set_write_timeout(Some(Duration::from_millis(500)))
        .ok()?;
    stream
        .write_all(b"GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .ok()?;

    let mut response = String::new();
    stream.read_to_string(&mut response).ok()?;
    let (headers, body) = response.split_once("\r\n\r\n")?;
    if !headers.starts_with("HTTP/1.1 200") && !headers.starts_with("HTTP/1.0 200") {
        return None;
    }
    serde_json::from_str(body).ok()
}

fn wait_for_backend_ready(
    child: &mut Child,
    instance_id: &str,
    backend_version: &str,
) -> Result<(), String> {
    let deadline = Instant::now() + BACKEND_START_TIMEOUT;
    while Instant::now() < deadline {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("检查后端进程失败: {error}"))?
        {
            return Err(format!("后端启动后提前退出: {status}"));
        }
        if let Some(identity) = fetch_backend_identity() {
            if backend_identity_matches(
                &identity,
                child.id(),
                std::process::id(),
                instance_id,
                backend_version,
            ) {
                return Ok(());
            }
        }
        thread::sleep(Duration::from_millis(150));
    }
    Err("等待新版后端健康检查超时".to_string())
}

fn stop_child(mut child: Child) -> Result<(), String> {
    let pid = child.id();
    // 新版后端监督线程会在写端关闭时读到 EOF，并请求 Uvicorn 优雅退出。
    drop(child.stdin.take());

    let deadline = Instant::now() + BACKEND_STOP_TIMEOUT;
    while Instant::now() < deadline {
        match child.try_wait() {
            Ok(Some(_)) => {
                eprintln!("[tauri] backend stopped pid={pid}");
                return Ok(());
            }
            Ok(None) => thread::sleep(Duration::from_millis(100)),
            Err(error) => return Err(format!("等待后端退出失败: {error}")),
        }
    }

    eprintln!("[tauri] backend graceful stop timed out; killing pid={pid}");
    match child.kill() {
        Ok(()) => {}
        Err(error) => {
            if child
                .try_wait()
                .map_err(|wait_error| format!("检查后端退出状态失败: {wait_error}"))?
                .is_none()
            {
                return Err(format!("强制结束后端失败: {error}"));
            }
        }
    }
    child
        .wait()
        .map_err(|error| format!("回收后端进程失败: {error}"))?;
    Ok(())
}

fn stop_managed_backend(backend: &Backend) -> Result<(), String> {
    let child = backend
        .0
        .lock()
        .map_err(|_| "后端进程状态锁已损坏".to_string())?
        .take();
    match child {
        Some(child) => stop_child(child),
        None => Ok(()),
    }
}

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
    // tauri.conf.json 把 packaging/dist/daxi 映射到资源目录的 backend/。
    // 兼容旧的 daxi/ 布局（手工 bundle 脚本产物）。
    ["backend", "daxi"]
        .iter()
        .map(|sub| resource_dir.join(sub).join(exe_name))
        .find(|p| p.exists())
}

/// 启动后端。dev 模式（无打包资源）下跳过：开发时手动 `daxi serve`。
fn spawn_backend(app: &AppHandle) -> Result<Option<Child>, String> {
    let exe = match backend_exe(app) {
        Some(p) => p,
        None => {
            eprintln!("[tauri] 未找到打包后端 exe，跳过自动启动（dev 模式请手动运行 daxi serve）");
            return Ok(None);
        }
    };

    // 开发模式允许使用手动启动的源码后端；生产包必须接管端口并验证实例。
    #[cfg(debug_assertions)]
    if port_is_listening() {
        eprintln!("[tauri] dev backend already listening; skip bundled backend");
        return Ok(None);
    }
    prepare_backend_port()?;

    eprintln!("[tauri] launching backend: {}", exe.display());
    let instance_id = new_instance_id();
    let backend_version = app.package_info().version.to_string();
    let mut cmd = Command::new(&exe);
    cmd.arg("serve")
        .arg("--host")
        .arg("127.0.0.1")
        .arg("--port")
        .arg(BACKEND_PORT.to_string())
        .arg("--supervised")
        .env("DAXI_PARENT_PID", std::process::id().to_string())
        .env("DAXI_INSTANCE_ID", &instance_id)
        .env("DAXI_DESKTOP_VERSION", &backend_version)
        .stdin(Stdio::piped());

    // Windows：后端 exe 是 console=True，直接拉起会弹 cmd 黑窗。
    // CREATE_NO_WINDOW (0x0800_0000) 抑制控制台窗口。
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = cmd
        .spawn()
        .map_err(|error| format!("启动后端失败: {error}"))?;
    if let Err(error) = wait_for_backend_ready(&mut child, &instance_id, &backend_version) {
        let _ = stop_child(child);
        return Err(error);
    }
    eprintln!(
        "[tauri] backend ready pid={} instance={instance_id}",
        child.id()
    );
    Ok(Some(child))
}

fn main() {
    tauri::Builder::default()
        // 必须排在所有插件和 setup 前：第二个桌面实例不能进入后端回收逻辑。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            let child = spawn_backend(&handle).map_err(std::io::Error::other)?;
            let state: State<Backend> = app.state();
            *state.0.lock().unwrap() = child;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // 只在不可撤销的最终 Exit 清理；ExitRequested 可能被插件阻止。
            // 即便进程被强杀来不及进入这里，stdin 监督管道也会自动关闭，
            // 后端会自行退出。
            if let RunEvent::Exit = event {
                let state: State<Backend> = app_handle.state();
                if let Err(error) = stop_managed_backend(&state) {
                    eprintln!("[tauri] backend cleanup failed: {error}");
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use super::{
        backend_identity_matches, is_daxi_backend_command, BackendIdentity, BACKEND_API_PROTOCOL,
        BACKEND_PORT, BACKEND_SERVICE_ID,
    };

    fn command(args: &[&str]) -> Vec<String> {
        args.iter().map(|value| (*value).to_string()).collect()
    }

    #[test]
    fn matches_managed_backend_command() {
        let args = command(&[
            "/Applications/Daolue.app/Contents/Resources/backend/daxi",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            &BACKEND_PORT.to_string(),
        ]);
        assert!(is_daxi_backend_command("daxi", &args));
        assert!(is_daxi_backend_command("DAXI.EXE", &args));
    }

    #[test]
    fn accepts_equals_style_options() {
        let args = command(&["daxi.exe", "serve", "--host=127.0.0.1", "--port=8756"]);
        assert!(is_daxi_backend_command("daxi.exe", &args));
    }

    #[test]
    fn rejects_unrelated_daxi_commands_and_processes() {
        let crawl = command(&["daxi", "crawl", "--host", "127.0.0.1", "--port", "8756"]);
        let other_port = command(&["daxi", "serve", "--host", "127.0.0.1", "--port", "9000"]);
        let other_program = command(&["other", "serve", "--host", "127.0.0.1", "--port", "8756"]);
        assert!(!is_daxi_backend_command("daxi", &crawl));
        assert!(!is_daxi_backend_command("daxi", &other_port));
        assert!(!is_daxi_backend_command("other", &other_program));
    }

    #[test]
    fn health_identity_rejects_old_or_unrelated_backend() {
        let mut identity = BackendIdentity {
            service_id: BACKEND_SERVICE_ID.to_string(),
            api_protocol: BACKEND_API_PROTOCOL,
            backend_version: "1.2.3".to_string(),
            pid: 200,
            parent_pid: Some(100),
            instance_id: "instance-abc".to_string(),
        };
        assert!(backend_identity_matches(
            &identity,
            200,
            100,
            "instance-abc",
            "1.2.3"
        ));

        identity.backend_version = "1.2.2".to_string();
        assert!(!backend_identity_matches(
            &identity,
            200,
            100,
            "instance-abc",
            "1.2.3"
        ));
        identity.backend_version = "1.2.3".to_string();
        identity.pid = 201;
        assert!(!backend_identity_matches(
            &identity,
            200,
            100,
            "instance-abc",
            "1.2.3"
        ));
    }
}
