//! A visible Chromium window in a disposable profile, approved on the computer.
//! Only targets created here are reachable; no user debugging port is exposed.

use futures_util::{SinkExt, StreamExt};
use serde_json::{Map, Value};
use std::{collections::HashMap, path::PathBuf, process::Stdio, sync::Arc};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::{net::TcpStream, sync::Mutex};
use tokio_tungstenite::{
    tungstenite::{protocol::WebSocketConfig, Message},
    MaybeTlsStream, WebSocketStream,
};

#[derive(Default)]
pub struct Browsers(Mutex<Registry>);
#[derive(Default)]
struct Registry {
    generation: u64,
    windows: HashMap<String, Browser>,
}
type CdpSocket = WebSocketStream<MaybeTlsStream<TcpStream>>;
struct CdpConnection {
    socket: CdpSocket,
    next_id: u64,
}
struct Browser {
    child: tokio::process::Child,
    profile: PathBuf,
    connection: Option<Arc<Mutex<CdpConnection>>>,
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

impl Browser {
    async fn close(&mut self) -> Result<(), String> {
        // Let Chromium close its renderer processes and flush the profile before
        // removing it. Killing the parent alone can leave child processes alive.
        let graceful = async {
            if let Some(connection) = &self.connection {
                let mut connection = connection.lock().await;
                let _ = connection
                    .socket
                    .send(Message::Text(
                        serde_json::json!({"id": 0, "method": "Browser.close"})
                            .to_string()
                            .into(),
                    ))
                    .await;
            }
        };
        let _ = tokio::time::timeout(std::time::Duration::from_secs(2), graceful).await;
        if !matches!(
            tokio::time::timeout(std::time::Duration::from_secs(3), self.child.wait()).await,
            Ok(Ok(_))
        ) {
            self.child.kill().await.map_err(|e| e.to_string())?;
        }
        tokio::fs::remove_dir_all(&self.profile)
            .await
            .map_err(|e| e.to_string())
    }
}

fn executable() -> Result<PathBuf, String> {
    #[cfg(target_os = "macos")]
    let candidates = vec![
        PathBuf::from("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        PathBuf::from("/Applications/Chromium.app/Contents/MacOS/Chromium"),
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
                PathBuf::from(&root).join("Microsoft/Edge/Application/msedge.exe"),
                PathBuf::from(root).join("BraveSoftware/Brave-Browser/Application/brave.exe"),
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
                root.join("microsoft-edge"),
                root.join("microsoft-edge-stable"),
                root.join("brave-browser"),
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
        connection: None,
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
            let config = WebSocketConfig::default()
                .max_message_size(Some(8 * 1024 * 1024))
                .max_frame_size(Some(8 * 1024 * 1024));
            let (socket, _) = tokio::time::timeout(
                std::time::Duration::from_secs(5),
                tokio_tungstenite::connect_async_with_config(&socket, Some(config), false),
            )
            .await
            .map_err(|_| "The local browser did not accept a connection.".to_owned())?
            .map_err(|e| e.to_string())?;
            browser.connection = Some(Arc::new(Mutex::new(CdpConnection { socket, next_id: 1 })));
            Ok((id, browser))
        }
        Err(error) => {
            if let Err(cleanup) = browser.close().await {
                eprintln!("Could not clean up a browser that failed to start: {cleanup}");
            }
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
    "Page.getNavigationHistory",
    "Page.navigateToHistoryEntry",
    "Page.reload",
    "Page.addScriptToEvaluateOnNewDocument",
    "Page.captureScreenshot",
    "Emulation.setDeviceMetricsOverride",
    "Emulation.setTimezoneOverride",
    "Emulation.setUserAgentOverride",
    "Emulation.setLocaleOverride",
];

pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    if args.get("engine").and_then(Value::as_str) == Some("native")
        || args
            .get("id")
            .and_then(Value::as_str)
            .is_some_and(|id| id.starts_with("native-browser-"))
    {
        return crate::native_browser::run(app, op, args).await;
    }
    if op == "browser.open" {
        let state = app.state::<Browsers>();
        let generation = state.0.lock().await.generation;
        let (id, mut browser) = start(app).await?;
        let mut registry = state.0.lock().await;
        if registry.generation != generation {
            drop(registry);
            browser.close().await?;
            return Err("The device disconnected while opening the browser.".into());
        }
        registry.windows.insert(id.clone(), browser);
        return serde_json::from_value(serde_json::json!({"id":id})).map_err(|e| e.to_string());
    }
    let id = args
        .get("id")
        .and_then(Value::as_str)
        .ok_or("Name this browse's window.")?;
    let state = app.state::<Browsers>();
    if op == "browser.close" {
        let browser = state.0.lock().await.windows.remove(id);
        if let Some(mut browser) = browser {
            browser.close().await?;
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
    let connection = state
        .0
        .lock()
        .await
        .windows
        .get(id)
        .ok_or("This browse has ended.")?
        .connection
        .clone()
        .ok_or("The local browser has no connection.")?;
    let params = args.get("params").cloned().unwrap_or_else(|| serde_json::json!({}));
    command(&connection, method, params).await
}

async fn command(
    connection: &Arc<Mutex<CdpConnection>>,
    method: &str,
    params: Value,
) -> Result<Map<String, Value>, String> {
    tokio::time::timeout(std::time::Duration::from_secs(30), async {
        // One CDP session per browse preserves emulation settings and scripts.
        // A cancelled request can leave a reply queued, so ids are never reused.
        let mut connection = connection.lock().await;
        let id = connection.next_id;
        connection.next_id = id
            .checked_add(1)
            .ok_or("This browser session reached its command limit.")?;
        connection
            .socket
            .send(Message::Text(
                serde_json::json!({"id":id,"method":method,"params":params})
                    .to_string()
                    .into(),
            ))
            .await
            .map_err(|e| e.to_string())?;
        while let Some(frame) = connection.socket.next().await {
            let Message::Text(text) = frame.map_err(|e| e.to_string())? else {
                continue;
            };
            let answer: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
            if answer.get("id").and_then(Value::as_u64) != Some(id) {
                continue;
            }
            if let Some(error) = answer.get("error") {
                if error
                    .get("message")
                    .and_then(Value::as_str)
                    .is_some_and(|message| message.contains("Execution context was destroyed"))
                {
                    return Err("Execution context was destroyed".into());
                }
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
    crate::native_browser::close_all(app).await;
    let state = app.state::<Browsers>();
    let browsers = {
        let mut registry = state.0.lock().await;
        // An open in progress belongs to the connection being closed, even if
        // its native consent dialog answers after this registry was drained.
        registry.generation = registry.generation.wrapping_add(1);
        std::mem::take(&mut registry.windows)
    };
    for (_, mut browser) in browsers {
        if let Err(error) = browser.close().await {
            eprintln!("Could not remove a local browser profile: {error}");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn commands_keep_one_connection_and_ignore_late_replies() {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            let (stream, _) = listener.accept().await.unwrap();
            let mut socket = tokio_tungstenite::accept_async(stream).await.unwrap();
            for (expected, value) in [(1, "one"), (2, "two")] {
                let request = socket.next().await.unwrap().unwrap().into_text().unwrap();
                let request: Value = serde_json::from_str(&request).unwrap();
                assert_eq!(request["id"], expected);
                if expected == 2 {
                    socket
                        .send(Message::Text(
                            serde_json::json!({"id":1,"result":{"value":"late"}}).to_string().into(),
                        ))
                        .await
                        .unwrap();
                }
                socket
                    .send(Message::Text(
                        serde_json::json!({"id":expected,"result":{"value":value}})
                            .to_string()
                            .into(),
                    ))
                    .await
                    .unwrap();
            }
        });
        let (socket, _) = tokio_tungstenite::connect_async(format!("ws://{address}"))
            .await
            .unwrap();
        let connection = Arc::new(Mutex::new(CdpConnection { socket, next_id: 1 }));
        let exchange = async {
            assert_eq!(
                command(&connection, "Runtime.evaluate", Value::Null).await.unwrap()["value"],
                "one"
            );
            assert_eq!(
                command(&connection, "Runtime.evaluate", Value::Null).await.unwrap()["value"],
                "two"
            );
            server.await.unwrap();
        };
        tokio::time::timeout(std::time::Duration::from_secs(3), exchange)
            .await
            .unwrap();
    }

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
