//! This computer as a device the person's own runs can work on (#2305).
//!
//! The shell - not the console's page - holds the connection. It redeems a
//! pairing code into a session of its own, keeps that session's refresh token in
//! the operating system's keychain, and opens the device hub's socket with it.
//! Nothing the console's page runs can send this computer an operation: a script
//! there could ask the shell to link, which the person confirms in a native
//! dialog naming the account, but never speak on the socket.
//!
//! The socket reconnects on its own - a laptop waking from sleep, a server
//! restarting - and stops for good only when the server refuses the session,
//! which is what "Disconnect" on the Devices screen does.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use agenticos_shell_core::device::{backoff, AppFrame, Capabilities, Endpoints, EndpointsAnswer, ServerFrame};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::{AppHandle, Emitter, Manager, Url};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::sync::{mpsc, Notify};
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::HeaderValue;
use tokio_tungstenite::tungstenite::Message;

use crate::settings;

const KEYCHAIN_SERVICE: &str = "AgenticOS";
/// How often the app says it is still there, between calls.
const PING_SECONDS: u64 = 25;
/// The event the console listens to for the connection's state.
pub const STATUS_EVENT: &str = "device-status";

#[cfg(target_os = "macos")]
const PLATFORM: &str = "macos";
#[cfg(target_os = "windows")]
const PLATFORM: &str = "windows";
#[cfg(all(not(target_os = "macos"), not(target_os = "windows")))]
const PLATFORM: &str = "linux";

/// The connection's state, held for the app's lifetime.
#[derive(Default)]
pub struct Device {
    connected: Mutex<bool>,
    stop: Mutex<Option<Arc<Notify>>>,
}

/// What the console shows on the Desktop app settings tab.
#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
pub struct DeviceStatus {
    /// This computer holds a session of its own for the chosen server.
    pub linked: bool,
    /// The socket is open right now.
    pub connected: bool,
}

#[derive(Deserialize)]
struct TokenPair {
    access_token: String,
    refresh_token: String,
}

#[derive(Deserialize)]
struct Me {
    email: String,
}

/// Why a connection attempt ended.
enum Ended {
    /// The server refused the session: signed out, or disconnected from Devices.
    Revoked,
    /// Anything that trying again can heal.
    Failed(String),
}

fn keychain(server: &Url) -> Result<keyring::Entry, String> {
    keyring::Entry::new(
        KEYCHAIN_SERVICE,
        &format!("device:{}", server.origin().ascii_serialization()),
    )
    .map_err(|e| format!("The keychain cannot be opened: {e}"))
}

fn stored_refresh(server: &Url) -> Option<String> {
    keychain(server).ok()?.get_password().ok()
}

fn store_refresh(server: &Url, token: &str) -> Result<(), String> {
    keychain(server)?
        .set_password(token)
        .map_err(|e| format!("The keychain refused the session: {e}"))
}

fn forget(server: &Url) {
    if let Ok(entry) = keychain(server) {
        let _ = entry.delete_credential();
    }
}

fn http() -> Result<reqwest::Client, String> {
    reqwest::Client::builder()
        .user_agent(format!("AgenticOS/{} ({PLATFORM})", env!("CARGO_PKG_VERSION")))
        .timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|e| e.to_string())
}

async fn endpoints(client: &reqwest::Client, server: &Url) -> Result<Endpoints, String> {
    let answer: EndpointsAnswer = client
        .get(Endpoints::discovery_url(server))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|_| "The server did not say where its API is.".to_owned())?
        .json()
        .await
        .map_err(|_| "The server's answer was not readable.".to_owned())?;
    Endpoints::from_answer(&answer)
}

async fn refresh(client: &reqwest::Client, endpoints: &Endpoints, token: &str) -> Result<TokenPair, Ended> {
    let response = client
        .post(endpoints.api_route("/api/v1/auth/refresh"))
        .json(&serde_json::json!({ "refresh_token": token }))
        .send()
        .await
        .map_err(|e| Ended::Failed(e.to_string()))?;
    match response.status().as_u16() {
        401 | 403 => Err(Ended::Revoked),
        status if status >= 400 => Err(Ended::Failed(format!("the server answered {status}"))),
        _ => response.json().await.map_err(|e| Ended::Failed(e.to_string())),
    }
}

fn status(app: &AppHandle) -> DeviceStatus {
    let linked = settings::current(app)
        .server_url
        .as_ref()
        .and_then(stored_refresh)
        .is_some();
    let connected = *app
        .state::<Device>()
        .connected
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    DeviceStatus { linked, connected }
}

fn set_connected(app: &AppHandle, value: bool) {
    *app.state::<Device>()
        .connected
        .lock()
        .unwrap_or_else(|e| e.into_inner()) = value;
    let _ = app.emit(STATUS_EVENT, status(app));
}

#[tauri::command]
pub fn device_status(app: AppHandle) -> DeviceStatus {
    status(&app)
}

/// Link this computer to the person's account with a pairing code the console minted.
///
/// The person confirms, in a native dialog naming the account, before anything is
/// stored: the code came from the console's page, and only the person at this
/// computer may decide whose runs work on it.
#[tauri::command]
pub async fn device_link(app: AppHandle, code: String) -> Result<DeviceStatus, String> {
    let server = settings::current(&app)
        .server_url
        .ok_or("Connect the app to a server first.")?;
    let client = http()?;
    let endpoints = endpoints(&client, &server).await?;
    let pair: TokenPair = client
        .post(endpoints.api_route("/api/v1/auth/pairing-codes/redeem"))
        .json(&serde_json::json!({ "code": code }))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|_| "That code has expired or was already used. Try again.".to_owned())?
        .json()
        .await
        .map_err(|e| e.to_string())?;
    let bearer = format!("Bearer {}", pair.access_token);
    let me: Me = client
        .get(endpoints.api_route("/api/v1/auth/me"))
        .header("Authorization", &bearer)
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|e| e.to_string())?
        .json()
        .await
        .map_err(|e| e.to_string())?;
    let host = server.host_str().unwrap_or("the server").to_owned();
    let (answered, answer) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!(
            "Agents of {} on {host} will be able to work on this computer when you choose \
             \"This computer\" in a chat - in the folder you pick, as the mode you pick allows.",
            me.email
        ))
        .title("Let your agents work on this computer?")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom("Allow".into(), "Cancel".into()))
        .show(move |allowed| {
            let _ = answered.send(allowed);
        });
    let confirmed = answer.await.unwrap_or(false);
    if !confirmed {
        let _ = client
            .post(endpoints.api_route("/api/v1/auth/logout"))
            .json(&serde_json::json!({ "refresh_token": pair.refresh_token }))
            .send()
            .await;
        return Err("Not linked.".to_owned());
    }
    // Named in the Devices list as the desktop app, which is what lets it hold a
    // device socket at all.
    client
        .put(endpoints.api_route("/api/v1/sessions/current/app"))
        .header("Authorization", &bearer)
        .json(&serde_json::json!({ "platform": PLATFORM, "version": env!("CARGO_PKG_VERSION") }))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
        .map_err(|e| e.to_string())?;
    store_refresh(&server, &pair.refresh_token)?;
    start(&app);
    Ok(status(&app))
}

/// Unlink this computer: its session ends on the server and the keychain forgets it.
#[tauri::command]
pub async fn device_unlink(app: AppHandle) -> Result<DeviceStatus, String> {
    stop(&app);
    if let Some(server) = settings::current(&app).server_url {
        if let Some(token) = stored_refresh(&server) {
            let client = http()?;
            if let Ok(endpoints) = endpoints(&client, &server).await {
                let _ = client
                    .post(endpoints.api_route("/api/v1/auth/logout"))
                    .json(&serde_json::json!({ "refresh_token": token }))
                    .send()
                    .await;
            }
        }
        forget(&server);
    }
    set_connected(&app, false);
    Ok(status(&app))
}

fn stop(app: &AppHandle) {
    if let Some(previous) = app
        .state::<Device>()
        .stop
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .take()
    {
        previous.notify_one();
    }
}

/// Connect, and keep connecting, if this computer is linked to the chosen server.
pub fn start(app: &AppHandle) {
    stop(app);
    let Some(server) = settings::current(app).server_url else {
        return;
    };
    if stored_refresh(&server).is_none() {
        return;
    }
    let stopper = Arc::new(Notify::new());
    *app.state::<Device>().stop.lock().unwrap_or_else(|e| e.into_inner()) = Some(stopper.clone());
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let mut failures = 0;
        loop {
            let ended = tokio::select! {
                _ = stopper.notified() => return,
                ended = connection(&app, &server) => ended,
            };
            set_connected(&app, false);
            match ended {
                Ended::Revoked => {
                    forget(&server);
                    let _ = app.emit(STATUS_EVENT, status(&app));
                    return;
                }
                Ended::Failed(reason) => {
                    eprintln!("The device connection ended: {reason}");
                    failures += 1;
                }
            }
            tokio::select! {
                _ = stopper.notified() => return,
                _ = tokio::time::sleep(backoff(failures)) => {}
            }
        }
    });
}

/// One connection, from a fresh access token to the socket's end.
async fn connection(app: &AppHandle, server: &Url) -> Ended {
    let Some(token) = stored_refresh(server) else {
        return Ended::Revoked;
    };
    let client = match http() {
        Ok(client) => client,
        Err(e) => return Ended::Failed(e),
    };
    let endpoints = match endpoints(&client, server).await {
        Ok(endpoints) => endpoints,
        Err(e) => return Ended::Failed(e),
    };
    let pair = match refresh(&client, &endpoints, &token).await {
        Ok(pair) => pair,
        Err(ended) => return ended,
    };
    if let Err(e) = store_refresh(server, &pair.refresh_token) {
        return Ended::Failed(e);
    }
    let mut request = match endpoints.device_socket().as_str().into_client_request() {
        Ok(request) => request,
        Err(e) => return Ended::Failed(e.to_string()),
    };
    let protocols = format!("device, access_token.{}", pair.access_token);
    match HeaderValue::from_str(&protocols) {
        Ok(value) => request.headers_mut().insert("Sec-WebSocket-Protocol", value),
        Err(e) => return Ended::Failed(e.to_string()),
    };
    let socket = match tokio_tungstenite::connect_async(request).await {
        Ok((socket, _)) => socket,
        Err(e) => return Ended::Failed(e.to_string()),
    };
    set_connected(app, true);
    serve(socket).await
}

async fn serve<S>(socket: tokio_tungstenite::WebSocketStream<S>) -> Ended
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin,
{
    let (mut write, mut read) = socket.split();
    let (answers, mut outgoing) = mpsc::unbounded_channel::<AppFrame>();
    let hello = AppFrame::Hello {
        version: env!("CARGO_PKG_VERSION").to_owned(),
        capabilities: capabilities(),
    };
    if let Err(e) = send(&mut write, &hello).await {
        return Ended::Failed(e);
    }
    let mut running: HashMap<String, tauri::async_runtime::JoinHandle<()>> = HashMap::new();
    let mut ping = tokio::time::interval(std::time::Duration::from_secs(PING_SECONDS));
    loop {
        tokio::select! {
            received = read.next() => {
                let text = match received {
                    Some(Ok(Message::Text(text))) => text,
                    Some(Ok(Message::Close(frame))) => {
                        // 4403: the session is no longer one that may hold a computer.
                        let refused = frame.as_ref().is_some_and(|f| u16::from(f.code) == 4403);
                        return if refused { Ended::Revoked } else { Ended::Failed("the server closed the socket".into()) };
                    }
                    Some(Ok(_)) => continue,
                    Some(Err(e)) => return Ended::Failed(e.to_string()),
                    None => return Ended::Failed("the socket ended".into()),
                };
                match serde_json::from_str::<ServerFrame>(&text) {
                    Ok(ServerFrame::Call { id, op, args }) => {
                        running.retain(|_, task| !task.inner().is_finished());
                        let answers = answers.clone();
                        let call_id = id.clone();
                        let task = tauri::async_runtime::spawn(async move {
                            let outcome = run(&op, args).await;
                            let _ = answers.send(AppFrame::answer(call_id, outcome));
                        });
                        running.insert(id, task);
                    }
                    Ok(ServerFrame::Cancel { id }) => {
                        if let Some(task) = running.remove(&id) {
                            task.abort();
                        }
                    }
                    Err(_) => continue,
                }
            }
            Some(answer) = outgoing.recv() => {
                if let Err(e) = send(&mut write, &answer).await {
                    return Ended::Failed(e);
                }
            }
            _ = ping.tick() => {
                if let Err(e) = send(&mut write, &AppFrame::Ping).await {
                    return Ended::Failed(e);
                }
            }
        }
    }
}

async fn send<W>(write: &mut W, frame: &AppFrame) -> Result<(), String>
where
    W: futures_util::Sink<Message> + Unpin,
    W::Error: std::fmt::Display,
{
    let text = serde_json::to_string(frame).map_err(|e| e.to_string())?;
    write.send(Message::Text(text.into())).await.map_err(|e| e.to_string())
}

/// What this computer can do today. The local sandbox and screen control add
/// themselves here as they land.
fn capabilities() -> Capabilities {
    Capabilities::default()
}

/// Run one operation the server asked for.
async fn run(op: &str, _args: Map<String, Value>) -> Result<Map<String, Value>, String> {
    match op {
        "system.info" => {
            let mut value = Map::new();
            value.insert("platform".into(), PLATFORM.into());
            value.insert("version".into(), env!("CARGO_PKG_VERSION").into());
            Ok(value)
        }
        other => Err(format!(
            "This computer's app does not do {other} yet. Update AgenticOS."
        )),
    }
}
