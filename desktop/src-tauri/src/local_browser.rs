//! A visible Chromium window in a disposable profile, approved on the computer.
//! Only targets created here are reachable; no user debugging port is exposed.

use futures_util::{SinkExt, StreamExt};
use serde_json::{Map, Value};
use std::{collections::HashMap, path::PathBuf, process::Stdio};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::sync::Mutex;
use tokio_tungstenite::tungstenite::Message;

#[derive(Default)]
pub struct Browsers(Mutex<HashMap<String, Browser>>);
struct Browser {
    child: tokio::process::Child,
    profile: PathBuf,
    socket: String,
}
impl Drop for Browser {
    fn drop(&mut self) {
        let _ = self.child.start_kill();
        let profile = self.profile.clone();
        tauri::async_runtime::spawn(async move {
            for _ in 0..20 {
                match tokio::fs::remove_dir_all(&profile).await {
                    Ok(()) => return,
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => return,
                    Err(_) => tokio::time::sleep(std::time::Duration::from_millis(100)).await,
                }
            }
            eprintln!("Could not remove a temporary local browser profile after stopping Chromium.");
        });
    }
}

fn executable() -> Result<PathBuf, String> {
    #[cfg(target_os = "macos")]
    let candidates = vec![
        PathBuf::from("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        PathBuf::from("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        PathBuf::from("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
    ];
    #[cfg(target_os = "windows")]
    let candidates: Vec<PathBuf> = ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]
        .into_iter()
        .filter_map(std::env::var_os)
        .flat_map(|root| {
            [
                PathBuf::from(&root).join("Google/Chrome/Application/chrome.exe"),
                PathBuf::from(root).join("Microsoft/Edge/Application/msedge.exe"),
            ]
        })
        .collect();
    #[cfg(target_os = "linux")]
    let candidates: Vec<PathBuf> = std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
        .flat_map(|root| {
            [
                root.join("chromium"),
                root.join("chromium-browser"),
                root.join("google-chrome"),
            ]
        })
        .collect();
    candidates
        .into_iter()
        .find(|path| path.is_file())
        .ok_or_else(|| "Install Chrome, Chromium, Edge or Brave to browse on this computer.".into())
}

async fn http() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|e| e.to_string())
}

async fn start(app: &AppHandle) -> Result<(String, Browser), String> {
    let binary = executable()?;
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog().message("Allow your agent to open and control a local browser window? It uses a separate temporary profile, can reach websites and local network apps, and closes when the browse ends. Your personal browser tabs and saved passwords are not shared.")
        .title("Browse on this computer?").kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Open browser".into(), "Cancel".into()))
        .show(move |allowed| { let _ = send.send(allowed); });
    if !receive.await.unwrap_or(false) {
        return Err("Local browsing was cancelled.".into());
    }
    let id = uuid::Uuid::new_v4().to_string();
    let profile = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("browsers")
        .join(&id);
    std::fs::create_dir_all(&profile).map_err(|e| e.to_string())?;
    let child = tokio::process::Command::new(binary)
        .args([
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
            "--no-first-run",
            "--no-default-browser-check",
        ])
        .arg(format!("--user-data-dir={}", profile.display()))
        .arg("about:blank")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .kill_on_drop(true)
        .spawn()
        .map_err(|e| format!("Could not open the local browser: {e}"))?;
    let mut browser = Browser {
        child,
        profile,
        socket: String::new(),
    };
    let result = async {
        let client = http().await?;
        for _ in 0..100 {
            if browser.child.try_wait().map_err(|e| e.to_string())?.is_some() {
                return Err("The browser stopped before it was ready.".into());
            }
            if let Ok(active) = tokio::fs::read_to_string(browser.profile.join("DevToolsActivePort")).await {
                if let Some(port) = active.lines().next().and_then(|value| value.parse::<u16>().ok()) {
                    let tabs: Value = client
                        .get(format!("http://127.0.0.1:{port}/json/list"))
                        .send()
                        .await
                        .map_err(|e| e.to_string())?
                        .json()
                        .await
                        .map_err(|e| e.to_string())?;
                    if let Some(socket) = tabs
                        .as_array()
                        .and_then(|tabs| {
                            tabs.iter()
                                .find(|tab| tab.get("type").and_then(Value::as_str) == Some("page"))
                        })
                        .and_then(|tab| tab.get("webSocketDebuggerUrl"))
                        .and_then(Value::as_str)
                    {
                        let url = tauri::Url::parse(socket).map_err(|e| e.to_string())?;
                        if url.scheme() != "ws" || url.host_str() != Some("127.0.0.1") || url.port() != Some(port) {
                            return Err("The browser named an unexpected debugging address.".into());
                        }
                        return Ok(socket.to_owned());
                    }
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        }
        Err("The local browser did not become ready in time.".into())
    }
    .await;
    match result {
        Ok(socket) => {
            browser.socket = socket;
            Ok((id, browser))
        }
        Err(error) => {
            let _ = browser.child.kill().await;
            let _ = tokio::fs::remove_dir_all(&browser.profile).await;
            Err(error)
        }
    }
}

const METHODS: &[&str] = &[
    "Runtime.evaluate",
    "Input.dispatchMouseEvent",
    "Input.dispatchKeyEvent",
    "Input.insertText",
    "Page.navigate",
    "Page.captureScreenshot",
    "Emulation.setDeviceMetricsOverride",
];

pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    if op == "browser.open" {
        let (id, browser) = start(app).await?;
        app.state::<Browsers>().0.lock().await.insert(id.clone(), browser);
        return Ok(serde_json::from_value(serde_json::json!({"id":id})).map_err(|e| e.to_string())?);
    }
    let id = args
        .get("id")
        .and_then(Value::as_str)
        .ok_or("Name this browse's window.")?;
    let state = app.state::<Browsers>();
    if op == "browser.close" {
        let browser = state.0.lock().await.remove(id);
        if let Some(mut browser) = browser {
            let _ = browser.child.kill().await;
            tokio::fs::remove_dir_all(&browser.profile)
                .await
                .map_err(|e| e.to_string())?;
        }
        return Ok(Map::new());
    }
    if op != "browser.command" {
        return Err("Unknown local browser operation.".into());
    }
    let method = args
        .get("method")
        .and_then(Value::as_str)
        .ok_or("Name a browser operation.")?;
    if !METHODS.contains(&method) {
        return Err("This browser operation is not allowed.".into());
    }
    let socket = state
        .0
        .lock()
        .await
        .get(id)
        .ok_or("This browse has ended.")?
        .socket
        .clone();
    let params = args.get("params").cloned().unwrap_or_else(|| serde_json::json!({}));
    let (mut socket, _) = tokio_tungstenite::connect_async(&socket)
        .await
        .map_err(|e| e.to_string())?;
    socket
        .send(Message::Text(
            serde_json::json!({"id":1,"method":method,"params":params})
                .to_string()
                .into(),
        ))
        .await
        .map_err(|e| e.to_string())?;
    tokio::time::timeout(std::time::Duration::from_secs(30), async {
        while let Some(frame) = socket.next().await {
            let Message::Text(text) = frame.map_err(|e| e.to_string())? else {
                continue;
            };
            if text.len() > 8 * 1024 * 1024 {
                return Err("The browser response exceeded 8 MiB.".into());
            }
            let answer: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
            if answer.get("id").and_then(Value::as_u64) != Some(1) {
                continue;
            }
            if answer.get("error").is_some() {
                return Err("The local browser refused this operation.".into());
            }
            return answer
                .get("result")
                .and_then(Value::as_object)
                .cloned()
                .ok_or_else(|| "The browser returned an invalid answer.".into());
        }
        Err("The local browser disconnected.".into())
    })
    .await
    .map_err(|_| "The local browser timed out.".to_owned())?
}

pub async fn close_all(app: &AppHandle) {
    let state = app.state::<Browsers>();
    let browsers = std::mem::take(&mut *state.0.lock().await);
    for (_, mut browser) in browsers {
        let _ = browser.child.kill().await;
        if let Err(error) = tokio::fs::remove_dir_all(&browser.profile).await {
            eprintln!("Could not remove a local browser profile: {error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn local_browser_commands_cannot_extract_profile_secrets_or_start_a_process() {
        for method in [
            "Browser.close",
            "Storage.getCookies",
            "Target.createTarget",
            "Browser.getBrowserCommandLine",
        ] {
            assert!(!METHODS.contains(&method));
        }
        assert!(METHODS.contains(&"Runtime.evaluate"));
    }
}
