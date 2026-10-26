//! Conversation-owned WebViews. Pages may only notify that they took control.

use serde::Deserialize;
use serde_json::{json, Map, Value};
use std::{
    collections::HashMap,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::{Duration, Instant},
};
use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager, Webview, WebviewUrl};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};

const LIMIT: usize = 8;
const IDLE: Duration = Duration::from_secs(2 * 60 * 60);
const LEASE_IDLE: Duration = Duration::from_secs(120);
const MAX_REPLY: usize = 2 * 1024 * 1024;
const SCRIPT: &str = include_str!("native_browser_page.js");

#[derive(Default)]
pub struct NativeBrowsers(Mutex<Registry>, tokio::sync::Mutex<()>);
#[derive(Default)]
struct Registry {
    generation: u64,
    tabs: HashMap<String, Tab>,
}
struct Tab {
    scope: Option<String>,
    domains: Option<Vec<String>>,
    lease: Option<String>,
    touched: Instant,
    renewed: Instant,
    held: Arc<AtomicBool>,
    mount: Option<String>,
}

impl Tab {
    fn accepts(&self, lease: &str) -> bool {
        self.lease.as_deref() == Some(lease) && self.renewed.elapsed() < LEASE_IDLE
    }
}

struct UnpublishedView(Option<Webview>);
impl Drop for UnpublishedView {
    fn drop(&mut self) {
        if let Some(view) = self.0.take() {
            if let Err(error) = view.close() {
                eprintln!("Could not close an unpublished native tab: {error}");
            }
        }
    }
}

fn allowed(url: &tauri::Url, domains: &Option<Vec<String>>) -> bool {
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port() == Some(0)
    {
        return false;
    }
    let Some(host) = url.host_str() else {
        return false;
    };
    match domains {
        None => true,
        Some(patterns) => patterns.iter().any(|pattern| {
            glob::Pattern::new(&pattern.to_ascii_lowercase())
                .is_ok_and(|pattern| pattern.matches(&host.to_ascii_lowercase()))
        }),
    }
}

fn page(app: &AppHandle, id: &str) -> Result<Webview, String> {
    app.get_webview(id)
        .ok_or_else(|| "This native browser tab is closed.".into())
}

async fn evaluated(view: &Webview, script: String) -> Result<Value, String> {
    let (send, receive) = tokio::sync::oneshot::channel();
    let send = Mutex::new(Some(send));
    view.eval_with_callback(script, move |raw| {
        if let Some(send) = send.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = send.send(raw);
        }
    })
    .map_err(|e| e.to_string())?;
    let raw = tokio::time::timeout(Duration::from_secs(5), receive)
        .await
        .map_err(|_| "The native browser did not answer.".to_owned())?
        .map_err(|_| "The native browser closed during evaluation.".to_owned())?;
    if raw.len() > MAX_REPLY {
        return Err("The browser reply exceeded its size limit.".into());
    }
    let value: Value = serde_json::from_str(&raw).map_err(|_| "The native browser returned an invalid reply.")?;
    match value {
        Value::String(text) => {
            serde_json::from_str(&text).map_err(|_| "The native browser returned invalid data.".into())
        }
        value => Ok(value),
    }
}

struct EvaluationSlot {
    view: Webview,
    key: String,
}
impl Drop for EvaluationSlot {
    fn drop(&mut self) {
        if let Err(error) = self.view.eval(format!("delete window[{}]", self.key)) {
            eprintln!("Could not remove a browser evaluation slot: {error}");
        }
    }
}

async fn evaluate(view: &Webview, expression: &str) -> Result<Value, String> {
    evaluate_inner(view, expression, false).await
}
async fn evaluate_navigation(view: &Webview, expression: &str) -> Result<Value, String> {
    evaluate_inner(view, expression, true).await
}
async fn evaluate_inner(view: &Webview, expression: &str, navigation: bool) -> Result<Value, String> {
    let document = evaluated(view, "JSON.stringify(String(performance.timeOrigin))".into()).await?;
    // Poll a bounded promise slot: native engines differ in whether their eval
    // callback awaits a JavaScript Promise. Results never travel through page IPC.
    let key = format!("__agenticos_result_{}", uuid::Uuid::new_v4().simple());
    let key_js = serde_json::to_string(&key).map_err(|e| e.to_string())?;
    let _slot = EvaluationSlot {
        view: view.clone(),
        key: key_js.clone(),
    };
    view.eval(format!(r#"(() => {{const key={key_js}; window[key]=null; Promise.resolve().then(() => (
{expression}
)).then(value => window[key]={{ok:true,value:value === undefined ? null : value}}, () => window[key]={{ok:false}});}})()"#)).map_err(|e| e.to_string())?;
    let result = tokio::time::timeout(Duration::from_secs(7), async {
        loop {
            let result = evaluated(view, format!("JSON.stringify(window[{key_js}] || null)")).await?;
            if !result.is_null() {
                return if result.get("ok").and_then(Value::as_bool) == Some(true) {
                    Ok(result.get("value").cloned().unwrap_or(Value::Null))
                } else {
                    Err("The page could not complete this script.".to_owned())
                };
            }
            let current = evaluated(view, "JSON.stringify(String(performance.timeOrigin))".into()).await?;
            if current != document {
                return if navigation {
                    Ok(Value::Null)
                } else {
                    Err("Execution context was destroyed".to_owned())
                };
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .unwrap_or_else(|_| Err("The native page timed out.".to_owned()));
    result
}

pub async fn open(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    let scope = args.get("scope").and_then(Value::as_str).map(str::to_owned);
    if scope
        .as_ref()
        .is_some_and(|s| s.len() != 64 || !s.bytes().all(|b| b.is_ascii_hexdigit()))
    {
        return Err("Invalid browser conversation scope.".into());
    }
    let domains: Option<Vec<String>> =
        serde_json::from_value(args.get("allowed_domains").cloned().unwrap_or(Value::Null))
            .map_err(|_| "Invalid browser domains.")?;
    let state = app.state::<NativeBrowsers>();
    let mut expired = Vec::new();
    let generation;
    {
        let mut registry = state.0.lock().map_err(|e| e.to_string())?;
        generation = registry.generation;
        registry.tabs.retain(|id, tab| {
            let active = tab.lease.as_deref().is_some_and(|lease| tab.accepts(lease));
            let lost_run = tab.lease.is_some() && !active;
            if lost_run {
                tab.lease = None;
            }
            let keep = app.get_webview(id).is_some()
                && !(lost_run && tab.scope.is_none())
                && (active || tab.touched.elapsed() < IDLE);
            if !keep {
                expired.push(id.clone());
            }
            keep
        });
    }
    for id in expired {
        if let Some(view) = app.get_webview(&id) {
            if let Err(error) = view.close() {
                eprintln!("Could not close an idle native tab: {error}");
            }
        }
    }
    {
        let mut registry = state.0.lock().map_err(|e| e.to_string())?;
        if registry.generation != generation {
            return Err("The browser connection changed.".into());
        }
        for (id, tab) in &mut registry.tabs {
            if scope.is_some() && tab.scope == scope {
                if tab.domains != domains {
                    return Err(
                        "This conversation's browser policy changed. Close its tab before reopening it.".into(),
                    );
                }
                if tab.lease.is_some() {
                    return Err("Another run is using this conversation's browser. Wait for it to finish; a stopped run's lease expires after two minutes.".into());
                }
                let lease = uuid::Uuid::new_v4().to_string();
                tab.lease = Some(lease.clone());
                tab.touched = Instant::now();
                tab.renewed = Instant::now();
                return Ok(json!({"id":id,"lease":lease,"native":true,"reused":true})
                    .as_object()
                    .unwrap()
                    .clone());
            }
        }
        if registry.tabs.len() >= LIMIT {
            return Err("Close an open browser tab before opening another (limit: 8).".into());
        }
    }
    if args.get("resume").and_then(Value::as_bool) == Some(true) {
        return Err("No browser tab is open for this conversation.".into());
    }
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog().message("Allow this agent to use a browser tab inside AgenticOS? It has a separate private session and can reach websites and local network apps. The tab stays open between messages until you close it or disconnect this computer. Your personal browser is not shared.")
        .title("Open an AgenticOS browser tab?").buttons(MessageDialogButtons::OkCancel)
        .show(move |yes| { let _ = send.send(yes); });
    if !receive.await.unwrap_or(false) {
        return Err("Local browsing was cancelled.".into());
    }
    let target = args
        .get("start_url")
        .and_then(Value::as_str)
        .ok_or("Name the browser's initial address.")?;
    create(app, generation, scope, domains, target).await
}

/// Called only after native consent; also exercised by the isolated smoke binary.
pub(crate) async fn create(
    app: &AppHandle,
    generation: u64,
    scope: Option<String>,
    domains: Option<Vec<String>>,
    start_url: &str,
) -> Result<Map<String, Value>, String> {
    let target: tauri::Url = start_url.parse().map_err(|_| "Use a web address.")?;
    if !allowed(&target, &domains) {
        return Err("This address is outside the agent's allowed domains.".into());
    }
    let state = app.state::<NativeBrowsers>();
    let id = format!("native-browser-{}", uuid::Uuid::new_v4().simple());
    app.add_capability(
        tauri::ipc::CapabilityBuilder::new(format!("input-{id}"))
            .local(false)
            .remote("https://*:*/*".into())
            .remote("http://*:*/*".into())
            .webview(id.clone())
            .permission("allow-native-browser-input"),
    )
    .map_err(|e| e.to_string())?;
    let ready = Arc::new(AtomicBool::new(false));
    let loaded = ready.clone();
    let policy = domains.clone();
    let held = Arc::new(AtomicBool::new(false));
    let data_directory = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join("native-browsers")
        .join(&id);
    let builder = tauri::webview::WebviewBuilder::new(&id, WebviewUrl::External(target))
        .incognito(true)
        .data_directory(data_directory)
        .initialization_script(SCRIPT)
        .on_page_load(move |_, payload| {
            if matches!(payload.event(), tauri::webview::PageLoadEvent::Finished) {
                loaded.store(true, Ordering::SeqCst);
            }
        })
        // Takeover comes from physical input or console controls. Redirects and
        // delayed page navigations must not impersonate a person's takeover.
        .on_navigation(move |url| allowed(url, &policy))
        .on_new_window(|_, _| tauri::webview::NewWindowResponse::Deny);
    let window = app
        .get_window(crate::WINDOW)
        .ok_or("Open the console before opening its browser.")?;
    let view = window
        .add_child(
            builder,
            LogicalPosition::new(0.0, 80.0),
            LogicalSize::new(1000.0, 650.0),
        )
        .map_err(|e| e.to_string())?;
    let mut unpublished = UnpublishedView(Some(view.clone()));
    view.hide().map_err(|e| e.to_string())?;
    // WKWebView has no URL before its first document. Wait for an interactive
    // page, rather than images/trackers completing the full load event.
    let initialized = tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if ready.load(Ordering::SeqCst) || matches!(evaluated(&view, "JSON.stringify(location.href !== 'about:blank' && !!window.__agenticosNative && document.readyState !== 'loading')".into()).await, Ok(Value::Bool(true))) { break; }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    }).await;
    if initialized.is_err() {
        return Err("The native browser did not load its initial document.".into());
    }
    let lease = uuid::Uuid::new_v4().to_string();
    let mut registry = state.0.lock().map_err(|e| e.to_string())?;
    // Consent and native creation yield. Check identity and capacity again before
    // publishing the new tab; disconnect invalidates opens already in flight.
    if registry.generation != generation
        || registry.tabs.len() >= LIMIT
        || scope
            .as_ref()
            .is_some_and(|scope| registry.tabs.values().any(|tab| tab.scope.as_ref() == Some(scope)))
    {
        drop(registry);
        return Err("The browser connection changed while opening its tab.".into());
    }
    registry.tabs.insert(
        id.clone(),
        Tab {
            scope,
            domains,
            lease: Some(lease.clone()),
            touched: Instant::now(),
            renewed: Instant::now(),
            held,
            mount: None,
        },
    );
    unpublished.0 = None;
    Ok(json!({"id":id,"lease":lease,"native":true,"reused":false})
        .as_object()
        .unwrap()
        .clone())
}

fn leased(app: &AppHandle, args: &Map<String, Value>) -> Result<String, String> {
    let id = args.get("id").and_then(Value::as_str).ok_or("Name the browser tab.")?;
    let lease = args
        .get("lease")
        .and_then(Value::as_str)
        .ok_or("Name the browser lease.")?;
    let state = app.state::<NativeBrowsers>();
    let mut registry = state.0.lock().map_err(|e| e.to_string())?;
    let tab = registry.tabs.get_mut(id).ok_or("This browser tab is closed.")?;
    if !tab.accepts(lease) {
        return Err("This browser lease has ended.".into());
    }
    tab.touched = Instant::now();
    tab.renewed = Instant::now();
    Ok(id.to_owned())
}

pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    if op == "browser.open" {
        return open(app, args).await;
    }
    if op == "browser.release" {
        let id = args.get("id").and_then(Value::as_str).ok_or("Name the browser tab.")?;
        let lease = args
            .get("lease")
            .and_then(Value::as_str)
            .ok_or("Name the browser lease.")?;
        let close = {
            let state = app.state::<NativeBrowsers>();
            let mut registry = state.0.lock().map_err(|e| e.to_string())?;
            let Some(tab) = registry.tabs.get_mut(id) else {
                return Ok(Map::new());
            };
            if tab.lease.is_none() {
                return Ok(Map::new());
            }
            if tab.lease.as_deref() != Some(lease) {
                return Err("This browser lease has ended.".into());
            }
            let close = tab.scope.is_none() || app.get_webview(id).is_none();
            if close {
                registry.tabs.remove(id);
            } else {
                tab.lease = None;
                tab.touched = Instant::now();
            }
            close
        };
        if close {
            if let Some(view) = app.get_webview(id) {
                view.close().map_err(|e| e.to_string())?;
            }
        }
        return Ok(Map::new());
    }
    let id = leased(app, args)?;
    if op == "browser.heartbeat" {
        return Ok(Map::new());
    }
    let view = page(app, &id)?;
    if op == "browser.control" {
        if let Some(held) = args.get("held").and_then(Value::as_bool) {
            set_held(app, &id, &view, held).await?;
        }
        return Ok(json!({"held":is_held(app, &id, &view).await?})
            .as_object()
            .unwrap()
            .clone());
    }
    let method = args
        .get("method")
        .and_then(Value::as_str)
        .ok_or("Name a browser operation.")?;
    let params = args.get("params").cloned().unwrap_or(json!({}));
    let result = match method {
        "Runtime.evaluate" => {
            let expression = params
                .get("expression")
                .and_then(Value::as_str)
                .ok_or("Name the expression.")?;
            let result = if args.get("native_action").and_then(Value::as_bool) == Some(true) {
                perform_action(app, &id, &view, expression).await?
            } else {
                evaluate(&view, expression).await?
            };
            json!({"result":{"value":result}})
        }
        "Page.navigate" => {
            if view.url().map_err(|e| e.to_string())?.as_str() != "about:blank" && is_held(app, &id, &view).await? {
                return Err("The person holds this browser. Wait for hand-back.".into());
            }
            let url = params.get("url").and_then(Value::as_str).ok_or("Name the address.")?;
            navigate(app, &id, url).await?;
            json!({"loaderId":uuid::Uuid::new_v4().to_string()})
        }
        "Page.reload" => {
            if is_held(app, &id, &view).await? {
                return Err("The person holds this browser. Wait for hand-back.".into());
            }
            view.reload().map_err(|e| e.to_string())?;
            json!({})
        }
        "Page.captureScreenshot" => {
            return Err(
                "Native DOM browsing does not provide screenshots. Use the Chromium browser for vision tasks.".into(),
            )
        }
        "Native.history" => {
            if is_held(app, &id, &view).await? {
                return Err("The person holds this browser. Wait for hand-back.".into());
            }
            let offset = params
                .get("offset")
                .and_then(Value::as_i64)
                .ok_or("Name the history direction.")?;
            if offset != -1 && offset != 1 {
                return Err("Invalid history direction.".into());
            }
            view.eval(format!("history.go({offset})")).map_err(|e| e.to_string())?;
            json!({})
        }
        "Input.dispatchMouseEvent" | "Input.dispatchKeyEvent" | "Input.insertText" => {
            perform_action(
                app,
                &id,
                &view,
                &format!(
                    "window.__agenticosNative.command({}, {})",
                    serde_json::to_string(method).unwrap(),
                    params
                ),
            )
            .await?;
            json!({})
        }
        _ => return Err("This native browser operation is not supported.".into()),
    };
    result
        .as_object()
        .cloned()
        .ok_or_else(|| "Invalid browser operation result.".into())
}

async fn perform_action(app: &AppHandle, id: &str, view: &Webview, expression: &str) -> Result<Value, String> {
    if is_held(app, id, view).await? {
        return Err("The person holds this browser. Wait for hand-back.".into());
    }
    let result = evaluate_navigation(
        view,
        &format!("window.__agenticosNative.action(() => (\n{expression}\n))"),
    )
    .await;
    result
}

async fn navigate(app: &AppHandle, id: &str, target: &str) -> Result<(), String> {
    let url: tauri::Url = target.parse().map_err(|_| "Use an HTTP or HTTPS address.")?;
    {
        let state = app.state::<NativeBrowsers>();
        let registry = state.0.lock().map_err(|e| e.to_string())?;
        let tab = registry.tabs.get(id).ok_or("This browser tab is closed.")?;
        if !allowed(&url, &tab.domains) {
            return Err("This address is outside the agent's allowed domains.".into());
        }
    }
    page(app, id)?.navigate(url).map_err(|e| e.to_string())
}

async fn set_held(app: &AppHandle, id: &str, view: &Webview, value: bool) -> Result<(), String> {
    {
        let state = app.state::<NativeBrowsers>();
        let registry = state.0.lock().map_err(|e| e.to_string())?;
        registry
            .tabs
            .get(id)
            .ok_or("This native tab is closed.")?
            .held
            .store(value, Ordering::SeqCst);
    }
    evaluate(view, &format!("window.__agenticosNative.setHeld({value})")).await?;
    Ok(())
}

async fn is_held(app: &AppHandle, id: &str, view: &Webview) -> Result<bool, String> {
    let flag = {
        let state = app.state::<NativeBrowsers>();
        let registry = state.0.lock().map_err(|e| e.to_string())?;
        registry.tabs.get(id).ok_or("This native tab is closed.")?.held.clone()
    };
    if evaluate(view, "window.__agenticosNative.held").await? == true {
        flag.store(true, Ordering::SeqCst);
    }
    Ok(flag.load(Ordering::SeqCst))
}

/// A browsed page can only pause its own agent; it cannot resume or name a tab.
#[tauri::command]
pub fn native_browser_input(app: AppHandle, webview: Webview) -> Result<(), String> {
    let state = app.state::<NativeBrowsers>();
    let registry = state.0.lock().map_err(|e| e.to_string())?;
    registry
        .tabs
        .get(webview.label())
        .ok_or("This native browser is closed.")?
        .held
        .store(true, Ordering::SeqCst);
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bounds {
    x: f64,
    y: f64,
    width: f64,
    height: f64,
}

#[tauri::command]
pub async fn native_browser_view(
    app: AppHandle,
    webview: Webview,
    id: String,
    action: String,
    bounds: Option<Bounds>,
    url: Option<String>,
    mount: Option<String>,
) -> Result<Value, String> {
    if webview.label() != crate::WINDOW {
        return Err("Only the console may show a native browser tab.".into());
    }
    let state = app.state::<NativeBrowsers>();
    let _renderer = if matches!(action.as_str(), "show" | "hide") {
        Some(state.1.lock().await)
    } else {
        None
    };

    if action == "hide" && app.get_webview(&id).is_none() {
        return Ok(Value::Null);
    }
    let view = page(&app, &id)?;
    {
        let state = app.state::<NativeBrowsers>();
        let mut registry = state.0.lock().map_err(|e| e.to_string())?;
        let tab = registry
            .tabs
            .get_mut(&id)
            .ok_or("This native tab is not available on this computer.")?;
        if action != "hide" {
            tab.touched = Instant::now();
        }
    }
    match action.as_str() {
        "show" => {
            let bounds = bounds.ok_or("Name the browser viewport.")?;
            let size = webview.window().inner_size().map_err(|e| e.to_string())?;
            let scale = webview.window().scale_factor().map_err(|e| e.to_string())?;
            if ![bounds.x, bounds.y, bounds.width, bounds.height]
                .iter()
                .all(|v| v.is_finite())
                || bounds.x < 0.0
                || bounds.y < 0.0
                || bounds.width < 1.0
                || bounds.height < 1.0
                || bounds.x + bounds.width > f64::from(size.width) / scale + 1.0
                || bounds.y + bounds.height > f64::from(size.height) / scale + 1.0
            {
                return Err("The browser viewport must fit inside the console.".into());
            }
            let mount = mount.as_deref().ok_or("Name the native renderer mount.")?;
            if mount.len() > 64 {
                return Err("Invalid native renderer mount.".into());
            }
            let hidden = {
                let mut registry = state.0.lock().map_err(|e| e.to_string())?;
                let hidden = registry
                    .tabs
                    .iter_mut()
                    .filter_map(|(other, tab)| {
                        if other != &id && tab.mount.take().is_some() {
                            Some(other.clone())
                        } else {
                            None
                        }
                    })
                    .collect::<Vec<_>>();
                registry.tabs.get_mut(&id).ok_or("This native tab is closed.")?.mount = Some(mount.to_owned());
                hidden
            };
            for other in hidden {
                if let Some(view) = app.get_webview(&other) {
                    view.hide().map_err(|e| e.to_string())?;
                }
            }
            view.set_position(LogicalPosition::new(bounds.x, bounds.y))
                .map_err(|e| e.to_string())?;
            view.set_size(LogicalSize::new(bounds.width, bounds.height))
                .map_err(|e| e.to_string())?;
            view.show().map_err(|e| e.to_string())?;
            let current = state
                .0
                .lock()
                .map_err(|e| e.to_string())?
                .tabs
                .get(&id)
                .and_then(|tab| tab.mount.clone());
            if current.as_deref() != Some(mount) {
                view.hide().map_err(|e| e.to_string())?;
            }
        }
        "hide" => {
            let hide = {
                let mut registry = state.0.lock().map_err(|e| e.to_string())?;
                let tab = registry.tabs.get_mut(&id).ok_or("This native tab is closed.")?;
                if tab.mount.is_some() && tab.mount == mount {
                    tab.mount = None;
                    true
                } else {
                    false
                }
            };
            if hide {
                view.hide().map_err(|e| e.to_string())?;
            }
        }
        "close" => {
            app.state::<NativeBrowsers>()
                .0
                .lock()
                .map_err(|e| e.to_string())?
                .tabs
                .remove(&id);
            view.close().map_err(|e| e.to_string())?;
        }
        "navigate" => {
            set_held(&app, &id, &view, true).await?;
            navigate(&app, &id, url.as_deref().ok_or("Name the address.")?).await?;
        }
        "back" | "forward" | "reload" => {
            set_held(&app, &id, &view, true).await?;
            match action.as_str() {
                "back" => view.eval("history.back()"),
                "forward" => view.eval("history.forward()"),
                _ => view.reload(),
            }
            .map_err(|e| e.to_string())?;
        }
        "take_over" | "give_back" => {
            set_held(&app, &id, &view, action == "take_over").await?;
        }
        "state" => {
            let mut state = evaluate(&view, "({url:location.href,title:document.title})").await?;
            state["held"] = json!(is_held(&app, &id, &view).await?);
            return Ok(state);
        }
        _ => return Err("Unknown native browser control.".into()),
    }
    Ok(Value::Null)
}

/// Native menu actions follow the visible browser instead of navigating the console.
pub fn handle_menu(app: &AppHandle, action: &str) -> Result<bool, String> {
    if !matches!(action, "back" | "forward" | "reload") {
        return Err("Unknown browser menu action.".into());
    }
    let active = {
        let state = app.state::<NativeBrowsers>();
        let registry = state.0.lock().map_err(|e| e.to_string())?;
        registry
            .tabs
            .iter()
            .find(|(_, tab)| tab.mount.is_some())
            .map(|(id, tab)| {
                tab.held.store(true, Ordering::SeqCst);
                id.clone()
            })
    };
    let Some(id) = active else {
        return Ok(false);
    };
    let view = page(app, &id)?;
    view.eval("window.__agenticosNative.setHeld(true)")
        .map_err(|e| e.to_string())?;
    match action {
        "back" => view.eval("history.back()"),
        "forward" => view.eval("history.forward()"),
        "reload" => view.reload(),
        _ => return Err("Unknown browser menu action.".into()),
    }
    .map_err(|e| e.to_string())?;
    Ok(true)
}

/// A full console navigation must not leave a child covering its new page.
pub fn hide_all(app: &AppHandle) {
    let ids = {
        let state = app.state::<NativeBrowsers>();
        let mut registry = state.0.lock().unwrap_or_else(|e| e.into_inner());
        registry
            .tabs
            .iter_mut()
            .map(|(id, tab)| {
                tab.mount = None;
                id.clone()
            })
            .collect::<Vec<_>>()
    };
    for id in ids {
        if let Some(view) = app.get_webview(&id) {
            if let Err(error) = view.hide() {
                eprintln!("Could not hide a native browser: {error}");
            }
        }
    }
}

pub async fn close_all(app: &AppHandle) {
    let tabs = {
        let state = app.state::<NativeBrowsers>();
        let mut registry = state.0.lock().unwrap_or_else(|e| e.into_inner());
        registry.generation = registry.generation.wrapping_add(1);
        std::mem::take(&mut registry.tabs)
    };
    for (id, _) in tabs {
        if let Some(view) = app.get_webview(&id) {
            if let Err(error) = view.close() {
                eprintln!("Could not close a native browser tab: {error}");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn navigation_only_reaches_allowed_web_origins() {
        let domains = Some(vec!["example.com".to_owned(), "*.example.com".to_owned()]);
        for target in ["https://example.com/", "http://sub.example.com:8080/"] {
            assert!(allowed(&target.parse().unwrap(), &domains));
        }
        for target in [
            "https://example.com.evil.test/",
            "https://evil-example.com/",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://user:password@example.com/",
            "https://example.com:0/",
        ] {
            assert!(!allowed(&target.parse().unwrap(), &domains));
        }
    }
    #[test]
    fn native_domains_preserve_empty_exact_and_wildcard_policy() {
        let address = |url: &str| url.parse::<tauri::Url>().unwrap();
        assert!(allowed(&address("https://elsewhere.test/"), &None));
        assert!(!allowed(&address("https://example.com/"), &Some(vec![])));
        assert!(!allowed(
            &address("https://sub.example.com/"),
            &Some(vec!["example.com".into()])
        ));
        assert!(!allowed(
            &address("https://example.com/"),
            &Some(vec!["*.example.com".into()])
        ));
        assert!(allowed(
            &address("https://SUB.EXAMPLE.COM/"),
            &Some(vec!["*.example.com".into()])
        ));
        assert!(allowed(
            &address("https://a1.example.com/"),
            &Some(vec!["a[12].example.com".into()])
        ));
    }
    #[test]
    fn a_lease_must_match_and_remain_fresh_before_renewal() {
        let mut tab = Tab {
            scope: Some("scope".into()),
            domains: None,
            lease: Some("lease".into()),
            touched: Instant::now(),
            renewed: Instant::now(),
            held: Arc::new(AtomicBool::new(false)),
            mount: None,
        };
        assert!(tab.accepts("lease"));
        assert!(!tab.accepts("different-run"));
        tab.renewed = Instant::now() - LEASE_IDLE - Duration::from_secs(1);
        assert!(!tab.accepts("lease"));
        tab.renewed = Instant::now();
        tab.lease = None;
        assert!(!tab.accepts("lease"));
    }
}
