//! AgenticOS on a phone: the deployment's console in a full-screen webview,
//! reached by scanning the QR the console shows (#2097).
//!
//! Like the desktop shell it remembers named server connections and opens the
//! console each server serves, with its own cookies and permissions. Native
//! pages handle first connection and server switching: scan a code or type an
//! address. What makes a sign-in this app's and nobody else's is shared with the
//! desktop shell, in `agenticos-shell-core`.
//!
//! The console is locked behind Face ID, Touch ID or the device's fingerprint
//! when the app comes back to the front after a while away.
//!
//! While an agent works or waits, the phone shows it outside the app (`live`);
//! a button there comes back as a link, and the console acts on it - a decision
//! only once the person is through the lock.

mod apns;
mod live;
mod managed;
mod navigation;
mod pin;
mod privacy;
mod push;
mod settings;
mod share;
use settings::Settings;
mod widget;

use std::fs;
use std::io::ErrorKind;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use agenticos_shell_core::{
    activity_link, external_sign_in_url, is_oauth_start, mint_nonce, pairing_link,
    parse_server_url_with, ActivityAction, ManagedPolicy, Mode, Pairing, PendingSignIn,
    SignInProof,
};
use serde::Serialize;
use tauri::webview::PageLoadEvent;
use tauri::{
    AppHandle, Emitter, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};
use tauri_plugin_biometric::{AuthOptions, BiometricExt};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_opener::OpenerExt;

const WINDOW: &str = "main";
const LOAD_TIMEOUT: Duration = Duration::from_secs(30);
/// After this long away, the console is locked again when the app returns.
const LOCK_AFTER: Duration = Duration::from_secs(5 * 60);
/// Plain `http` to the laptop beside the phone, in a development build only.
const LAN_HTTP: bool = cfg!(debug_assertions);
/// Told to the console when a live activity's button is waiting for it.
const ACTIVITY_EVENT: &str = "mobile:activity";

/// Where the settings file is, resolved once at start-up.
///
/// On Android the app's directories come from a Kotlin plugin over JNI, and
/// asking again from inside an event on the UI thread blocks that thread for
/// good - a white screen - so it is asked exactly once, in `setup`.
struct SettingsPath(PathBuf);

fn resolve_settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("No configuration directory: {e}"))?;
    Ok(dir.join("server.json"))
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.try_state::<SettingsPath>()
        .map(|path| path.0.clone())
        .ok_or_else(|| "The settings were asked for before the app started.".to_owned())
}

fn settings(app: &AppHandle) -> Settings {
    let Ok(path) = settings_path(app) else {
        return Settings::default();
    };
    match fs::read_to_string(&path) {
        Ok(raw) => serde_json::from_str(&raw).unwrap_or_default(),
        Err(e) if e.kind() == ErrorKind::NotFound => Settings::default(),
        Err(e) => {
            eprintln!("Cannot read {}: {e}", path.display());
            Settings::default()
        }
    }
}

fn save(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    let path = settings_path(app)?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("Cannot create {}: {e}", dir.display()))?;
    }
    let raw = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    fs::write(&path, raw).map_err(|e| format!("Cannot write {}: {e}", path.display()))
}

/// When the console was last unlocked, whether it is locked now, and what a
/// live activity's button asked of it - in one place, so a decision can never be
/// handed over in the moment between a lock and its veil.
#[derive(Default)]
struct Lock(Mutex<LockState>);

#[derive(Default)]
struct LockState {
    unlocked_at: Option<Instant>,
    locked: bool,
    asked: Option<ActivityAction>,
}

/// A live activity's button or a shortcut, as the console reads it from
/// `take_activity_action`.
#[derive(Serialize, Debug, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum Asked {
    Open { path: String },
    Start { mode: &'static str },
}

/// Hand the console what was asked - except, while it is locked, what needs
/// the person: approval review from a legacy link, or a microphone opened
/// from it, waits for the face behind it.
fn take_asked(state: &mut LockState) -> Option<Asked> {
    if state.locked
        && state
            .asked
            .as_ref()
            .is_some_and(ActivityAction::needs_presence)
    {
        return None;
    }
    state.asked.take().map(|action| match action {
        ActivityAction::Open(path) => Asked::Open { path },
        // Any process can invoke an activity URI; presence is not a decision.
        ActivityAction::Decide { .. } => Asked::Open {
            path: "/runs?tab=approvals".into(),
        },
        ActivityAction::Start(Mode::Call) => Asked::Start { mode: "call" },
        ActivityAction::Start(Mode::Dictate) => Asked::Start { mode: "dictate" },
    })
}

/// What a page needs to know about the shell before its first paint, as the
/// desktop shell announces itself: the console reads it to lay itself out for a
/// phone's screen.
fn shell_script(version: &str) -> String {
    let platform = if cfg!(target_os = "ios") {
        "ios"
    } else {
        "android"
    };
    format!(
        "Object.defineProperty(window, \"__AGENTICOS_SHELL__\", {{ value: Object.freeze({{\"platform\":\"{platform}\",\"version\":\"{version}\",\"window\":\"main\",\"vibrancy\":false}}) }});"
    )
}

/// The veil that hides the console while it is locked, with the one control on
/// it: a button that asks for the biometrics again, for a prompt somebody
/// dismissed. The call that removes it follows.
const LOCK_SCRIPT: &str = r#"(() => {
  if (document.getElementById("agenticos-lock")) return;
  const veil = document.createElement("div");
  veil.id = "agenticos-lock";
  veil.style.cssText = "position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;backdrop-filter:blur(30px) saturate(1.4);-webkit-backdrop-filter:blur(30px) saturate(1.4);background:color-mix(in oklab, Canvas 55%, transparent)";
  const unlock = document.createElement("button");
  unlock.textContent = "Unlock";
  unlock.style.cssText = "font:600 17px -apple-system,system-ui,sans-serif;padding:14px 32px;border:0;border-radius:14px;background:CanvasText;color:Canvas";
  unlock.addEventListener("click", () => window.__TAURI_INTERNALS__.invoke("unlock"));
  veil.appendChild(unlock);
  document.documentElement.appendChild(veil);
})();"#;
const UNLOCK_SCRIPT: &str = r#"document.getElementById("agenticos-lock")?.remove();"#;

/// Keep cached offline pages usable: this observes the webview load rather
/// than probing the network before it can open the service worker's copy.
fn watch_navigation(app: &AppHandle, url: &Url) -> Result<(), String> {
    let attempt = app.state::<navigation::Navigation>().begin()?;
    let origin = url.origin().ascii_serialization();
    let handle = app.clone();
    std::thread::spawn(move || {
        if attempt.cancelled.recv_timeout(LOAD_TIMEOUT)
            != Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        {
            return;
        }
        let recovery = handle.clone();
        if let Err(e) = handle.run_on_main_thread(move || {
            if !attempt.claim() {
                return;
            }
            let state = recovery.state::<navigation::Navigation>();
            if let Ok(mut notice) = state.notice.lock() {
                *notice = Some(format!(
                    "Could not load {origin}. Check your connection, then try again or enter another server."
                ));
            }
            let origin = if cfg!(target_os = "android") {
                "http://tauri.localhost"
            } else {
                "tauri://localhost"
            };
            let local = Url::parse(&format!("{origin}/index.html"))
                .expect("a literal onboarding URL parses");
            if let Err(e) = console(&recovery).and_then(|window| {
                window.navigate(local).map_err(|e| e.to_string())
            }) {
                eprintln!("Could not open connection recovery: {e}");
            }
        }) {
            eprintln!("Could not schedule connection recovery: {e}");
        }
    });
    Ok(())
}

fn navigate_console(app: &AppHandle, url: Url) -> Result<(), String> {
    let window = console(app)?;
    watch_navigation(app, &url)?;
    if let Err(e) = window.navigate(url) {
        app.state::<navigation::Navigation>().finish()?;
        return Err(e.to_string());
    }
    Ok(())
}

#[tauri::command]
fn startup_notice(app: AppHandle) -> Option<String> {
    app.state::<navigation::Navigation>()
        .notice
        .lock()
        .ok()
        .and_then(|mut notice| notice.take())
}

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    let handle = app.clone();
    let version = app.package_info().version.to_string();
    WebviewWindowBuilder::new(app, WINDOW, url)
        .initialization_script(shell_script(&version))
        // The veil lives in the page, so a page loaded while locked - a sign-in
        // returning, a pairing - is veiled again rather than opened by it.
        .on_page_load(|window, payload| {
            if payload.event() != PageLoadEvent::Finished {
                return;
            }
            if let Err(e) = window.state::<navigation::Navigation>().finish() {
                eprintln!("Could not finish navigation: {e}");
            }
            // Recovery contains no account content and must remain usable when
            // a failed remote page was locked behind biometrics.
            if payload.url().scheme() == "tauri"
                || payload.url().host_str() == Some("tauri.localhost")
            {
                return;
            }
            let locked = window
                .state::<Lock>()
                .0
                .lock()
                .map(|lock| lock.locked)
                .unwrap_or(false);
            if locked {
                if let Err(e) = window.eval(LOCK_SCRIPT) {
                    eprintln!("lock: {e}");
                }
            }
        })
        // The one navigation the webview refuses: a provider sign-in, handed to
        // the system browser and returned by deep link, as on the desktop (#1532).
        .on_navigation(move |url| {
            let server = settings(&handle).server_url;
            if !is_oauth_start(server.as_ref(), url) {
                return true;
            }
            if let Err(error) = handle.state::<SignInProof>().clear() {
                eprintln!("Could not start sign-in: {error}");
                return false;
            }
            let nonce = mint_nonce();
            if let Ok(mut pending) = handle.state::<PendingSignIn>().0.lock() {
                *pending = Some(nonce.clone());
            }
            if let Err(e) = handle
                .opener()
                .open_url(external_sign_in_url(url, &nonce).as_str(), None::<&str>)
            {
                eprintln!("Could not open the sign-in in your browser: {e}");
            }
            false
        })
        .build()
}

/// What the console - a remote page - may ask of the app: the unlock prompt
/// again, its live activities, what was shared with the app, the widget's
/// counts, a pinned agent, push, and a haptic tap. Granted for the configured
/// server's origin only, as the desktop shell grants its console's commands.
fn grant_console(app: &AppHandle, server: &Url) -> Result<(), String> {
    let pattern = format!("{}/*", server.origin().ascii_serialization());
    app.add_capability(
        tauri::ipc::CapabilityBuilder::new(format!("console-{pattern}"))
            .remote(pattern)
            .local(false)
            .window(WINDOW)
            .permission("allow-unlock")
            .permission("allow-mobile-settings")
            .permission("allow-oauth-verifier")
            .permission("allow-bind-push-session")
            .permission("allow-clear-push-session")
            .permission("allow-open-mobile-settings")
            .permission("allow-set-mobile-lock")
            .permission("allow-choose-server")
            .permission("allow-show-activity")
            .permission("allow-end-activity")
            .permission("allow-update-widget")
            .permission("allow-pin-shortcut")
            .permission("allow-push-status")
            .permission("allow-push-register")
            .permission("allow-push-unregister")
            .permission("allow-take-activity-action")
            .permission("allow-take-shared")
            .permission("allow-attach-sheet")
            .permission("allow-offer-recent-photo")
            .permission("allow-apns-status")
            .permission("allow-apns-register")
            .permission("allow-apns-unregister")
            // A tap under the finger when a swipe decides or a pull refreshes.
            .permission("haptics:allow-impact-feedback")
            .permission("haptics:allow-notification-feedback")
            .permission("haptics:allow-selection-feedback")
            .permission("core:event:allow-listen")
            .permission("core:event:allow-unlisten"),
    )
    .map_err(|e| e.to_string())
}

fn console(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window(WINDOW)
        .ok_or_else(|| "The app has no window.".to_owned())
}

/// The organization's device management, read once at start-up.
struct Managed(ManagedPolicy);

fn managed(app: &AppHandle) -> ManagedPolicy {
    app.try_state::<Managed>()
        .map(|managed| managed.0.clone())
        .unwrap_or_default()
}

/// Refuse a server the organization does not allow.
fn check_managed(app: &AppHandle, server: &Url) -> Result<(), String> {
    if managed(app).allows(server) {
        Ok(())
    } else {
        Err("Your organization manages which server this app connects to.".to_owned())
    }
}

/// Whether the console locks behind the biometrics: the organization's word
/// where it has one, the person's otherwise.
fn lock_enabled(app: &AppHandle, stored: &Settings) -> bool {
    managed(app).biometric_lock.unwrap_or(stored.lock)
}

/// Sign in with a scanned code: remember its console and send the webview to redeem it.
fn pair(app: &AppHandle, pairing: &Pairing) -> Result<(), String> {
    check_managed(app, &pairing.server)?;
    grant_console(app, &pairing.server)?;
    let mut stored = settings(app);
    stored.remember(pairing.server.clone(), None)?;
    save(app, &stored)?;
    navigate_console(app, pairing.redeem_url())
}

/// What the onboarding page shows first: an address already chosen, if any.
#[tauri::command]
fn oauth_verifier(app: AppHandle, code: String) -> Result<String, String> {
    app.state::<SignInProof>().take(&code)
}

#[tauri::command]
fn server_url(app: AppHandle) -> Option<Url> {
    settings(&app).server_url
}

/// A code the in-app scanner read.
#[tauri::command]
fn pair_with(app: AppHandle, link: String) -> Result<(), String> {
    pair(&app, &pairing_link(&link, LAN_HTTP)?)
}

/// An address typed by hand: remember it and open its sign-in page.
#[tauri::command]
fn connect(app: AppHandle, url: String, name: Option<String>) -> Result<(), String> {
    let server = parse_server_url_with(&url, LAN_HTTP)?;
    check_managed(&app, &server)?;
    grant_console(&app, &server)?;
    let mut stored = settings(&app);
    stored.remember(server.clone(), name)?;
    save(&app, &stored)?;
    let login = server.join("dashboard").map_err(|e| e.to_string())?;
    navigate_console(&app, login)
}

#[derive(Serialize)]
struct MobileSettings {
    servers: Vec<settings::Server>,
    active: Option<Url>,
    locked_server: bool,
    biometric_lock: bool,
    biometric_managed: bool,
    biometric_available: bool,
}

#[tauri::command]
async fn mobile_settings(app: AppHandle) -> Result<MobileSettings, String> {
    let mut stored = settings(&app);
    stored.migrate();
    let policy = managed(&app);
    // The full list has a separate command granted only to the bundled picker.
    let servers = stored
        .visible_servers(false)
        .into_iter()
        .filter(|s| policy.allows(&s.url))
        .collect();
    let handle = app.clone();
    let available = tauri::async_runtime::spawn_blocking(move || handle.biometric().status())
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())?
        .is_available;
    Ok(MobileSettings {
        active: stored.server_url.clone(),
        servers,
        locked_server: policy.server_locked,
        biometric_lock: lock_enabled(&app, &settings(&app)),
        biometric_managed: policy.biometric_lock.is_some(),
        biometric_available: available,
    })
}

#[tauri::command]
fn mobile_servers(app: AppHandle) -> Vec<settings::Server> {
    let mut stored = settings(&app);
    stored.migrate();
    let policy = managed(&app);
    stored
        .visible_servers(true)
        .into_iter()
        .filter(|s| policy.allows(&s.url))
        .collect()
}

#[tauri::command]
async fn set_mobile_lock(app: AppHandle, enabled: bool) -> Result<(), String> {
    if managed(&app).biometric_lock.is_some() {
        return Err("Your organization manages the app lock.".to_owned());
    }
    // Turning off protection is an authenticated action too.
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        handle.biometric().authenticate(
            "Change app lock".to_owned(),
            AuthOptions {
                allow_device_credential: true,
                ..Default::default()
            },
        )
    })
    .await
    .map_err(|e| e.to_string())?
    .map_err(|e| e.to_string())?;
    let mut stored = settings(&app);
    stored.lock = enabled;
    save(&app, &stored)
}

#[tauri::command]
async fn bind_push_session(app: AppHandle, session_id: String) -> Result<(), String> {
    if session_id.len() != 36
        || !session_id
            .chars()
            .all(|c| c.is_ascii_hexdigit() || c == '-')
    {
        return Err("The push connection identifier is invalid.".to_owned());
    }
    tauri::async_runtime::spawn_blocking(move || {
        #[cfg(target_os = "ios")]
        return apns::bind(&app, &session_id);
        #[cfg(target_os = "android")]
        return push::bind(&app, &session_id);
        #[cfg(not(mobile))]
        {
            let _ = (app, session_id);
            Ok(())
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Forget the signed-in recipient and remove notification previews from the phone.
#[tauri::command]
async fn clear_push_session(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || clear_push_binding(&app))
        .await
        .map_err(|e| e.to_string())?
}

fn clear_push_binding(app: &AppHandle) -> Result<(), String> {
    #[cfg(target_os = "ios")]
    return apns::bind(app, "");
    #[cfg(target_os = "android")]
    return push::bind(app, "");
    #[cfg(not(mobile))]
    {
        let _ = app;
        Ok(())
    }
}

#[tauri::command]
async fn open_mobile_settings(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || {
        #[cfg(target_os = "ios")]
        return apns::open_settings(&app);
        #[cfg(target_os = "android")]
        return push::open_settings(&app);
        #[cfg(not(mobile))]
        {
            let _ = app;
            Err("App settings are only available on a phone.".to_owned())
        }
    })
    .await
    .map_err(|e| e.to_string())?
}

#[tauri::command]
fn forget_server(app: AppHandle, url: String) -> Result<(), String> {
    let server = parse_server_url_with(&url, LAN_HTTP)?;
    let mut stored = settings(&app);
    if stored.server_url.as_ref() == Some(&server) {
        return Err("Switch to another server before removing this one.".to_owned());
    }
    stored.servers.retain(|s| s.url != server);
    save(&app, &stored)
}

#[tauri::command]
async fn choose_server(app: AppHandle) -> Result<(), String> {
    if managed(&app).server_locked {
        return Err("Your organization manages which server this app connects to.".to_owned());
    }
    app.state::<SignInProof>().clear()?;
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        clear_push_binding(&handle)?;
        live::clear(&handle)?;
        widget::clear(&handle)?;
        share::take(&handle)?;
        Ok::<(), String>(())
    })
    .await
    .map_err(|e| e.to_string())??;
    app.state::<navigation::Navigation>().finish()?;
    app.state::<PendingSignIn>()
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .take();
    app.state::<Lock>()
        .0
        .lock()
        .map_err(|e| e.to_string())?
        .asked = None;
    let origin = if cfg!(target_os = "android") {
        "http://tauri.localhost"
    } else {
        "tauri://localhost"
    };
    console(&app)?
        .navigate(Url::parse(&format!("{origin}/index.html")).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

/// Hide the console and ask for the device's biometrics; reveal it once they
/// answer. Whether the console is locked afterwards.
///
/// A phone with no biometrics enrolled falls back to its passcode
/// (`allow_device_credential`). One with neither is not locked: a lock nobody
/// can open is a broken app, not a safe one. A console already locked keeps
/// the prompt it has rather than stacking a second.
fn lock(app: &AppHandle) -> bool {
    let available = app
        .biometric()
        .status()
        .map(|status| status.is_available)
        .unwrap_or(false);
    if !available {
        return false;
    }
    let Ok(window) = console(app) else {
        return false;
    };
    if window
        .url()
        .is_ok_and(|url| url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost"))
    {
        return false;
    }
    let held = app.state::<Lock>();
    let Ok(mut state) = held.0.lock() else {
        return false;
    };
    if state.locked {
        return true;
    }
    state.locked = true;
    drop(state);
    if let Err(e) = window.eval(LOCK_SCRIPT) {
        eprintln!("lock: {e}");
    }
    ask_to_unlock(app);
    true
}

/// Tell the console something is waiting in `take_activity_action`.
fn nudge(app: &AppHandle) {
    if let Err(e) = app.emit_to(WINDOW, ACTIVITY_EVENT, ()) {
        eprintln!("activity: {e}");
    }
}

/// The biometric prompt, off the main thread. A dismissed prompt leaves the
/// console veiled, with the veil's own button to ask again.
fn ask_to_unlock(app: &AppHandle) {
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let options = AuthOptions {
            allow_device_credential: true,
            title: Some("Unlock AgenticOS".to_owned()),
            ..AuthOptions::default()
        };
        if let Err(e) = handle
            .biometric()
            .authenticate("Unlock AgenticOS".to_owned(), options)
        {
            eprintln!("unlock: {e}");
            return;
        }
        if let Ok(mut lock) = handle.state::<Lock>().0.lock() {
            lock.locked = false;
            lock.unlocked_at = Some(Instant::now());
        }
        if let Ok(window) = console(&handle) {
            if let Err(e) = window.eval(UNLOCK_SCRIPT) {
                eprintln!("unlock: {e}");
            }
        }
        // A decision that was waiting on this unlock can be made now.
        nudge(&handle);
    });
}

/// The veil's button: ask for the biometrics again, if the console is still locked.
#[tauri::command]
fn unlock(app: AppHandle) {
    let locked = app
        .state::<Lock>()
        .0
        .lock()
        .map(|lock| lock.locked)
        .unwrap_or(false);
    if locked {
        ask_to_unlock(&app);
    }
}

/// What a live activity's button asked, for the console to act on; see `take_asked`.
#[tauri::command]
fn take_activity_action(app: AppHandle) -> Option<Asked> {
    app.state::<Lock>()
        .0
        .lock()
        .ok()
        .and_then(|mut state| take_asked(&mut state))
}

/// What another app shared, for the console to put in a new message - but not
/// while it is locked: the composer uploads what it is given, at once.
#[tauri::command]
fn take_shared(app: AppHandle) -> Result<Option<share::Shared>, String> {
    let locked = app
        .state::<Lock>()
        .0
        .lock()
        .map(|state| state.locked)
        .unwrap_or(true);
    if locked {
        return Ok(None);
    }
    share::take(&app)
}

/// The composer's "+": on Android the phone's attach sheet - the camera, the
/// photo and file pickers, the latest photos to tick; on iOS the picker for the
/// source the console's sheet named. Answers with what the person chose.
#[tauri::command]
async fn attach_sheet(
    app: AppHandle,
    source: Option<share::Source>,
) -> Result<Option<share::Shared>, String> {
    ask_unless_locked(app, "openSheet", source).await
}

/// On opening the chat: a photo taken a moment ago, if the person adds it.
#[tauri::command]
async fn offer_recent_photo(app: AppHandle) -> Result<Option<share::Shared>, String> {
    ask_unless_locked(app, "offerRecent", None).await
}

/// Ask the attach plugin, off the main thread - it answers when the person
/// does - and never while the console is locked.
async fn ask_unless_locked(
    app: AppHandle,
    command: &'static str,
    source: Option<share::Source>,
) -> Result<Option<share::Shared>, String> {
    let locked = app
        .state::<Lock>()
        .0
        .lock()
        .map(|state| state.locked)
        .unwrap_or(true);
    if locked {
        return Ok(None);
    }
    tauri::async_runtime::spawn_blocking(move || share::ask(&app, command, source))
        .await
        .map_err(|e| e.to_string())?
}

/// A live activity's button or a shortcut: kept for the console, which is told
/// to come and take it. A decision, a call or dictation first puts the console
/// behind the lock, if it has one, so what is done from the lock screen is done
/// by whoever can unlock the phone.
fn on_activity(app: &AppHandle, action: ActivityAction) {
    let needs_presence = action.needs_presence();
    if let Ok(mut state) = app.state::<Lock>().0.lock() {
        state.asked = Some(action);
    }
    if needs_presence && lock_enabled(app, &settings(app)) && lock(app) {
        return;
    }
    nudge(app);
}

/// Whether coming back to the front should lock: long enough since the last unlock.
fn should_lock(lock_enabled: bool, unlocked_at: Option<Instant>, now: Instant) -> bool {
    lock_enabled && unlocked_at.map_or(true, |at| now.duration_since(at) >= LOCK_AFTER)
}

fn on_deep_link(app: &AppHandle, links: Vec<Url>) {
    let stored = settings(app);
    for link in links {
        if let Some(action) = activity_link(link.as_str()) {
            on_activity(app, action);
            return;
        }
        if let Ok(pairing) = pairing_link(link.as_str(), LAN_HTTP) {
            if let Err(e) = pair(app, &pairing) {
                eprintln!("pair: {e}");
            }
            return;
        }
        if let Some((destination, verifier)) = app
            .state::<PendingSignIn>()
            .finish(stored.server_url.as_ref(), link.as_str())
        {
            if let Err(error) = app.state::<SignInProof>().remember(&destination, &verifier) {
                eprintln!("Could not finish signing in: {error}");
                return;
            }
            if let Err(e) = navigate_console(app, destination) {
                eprintln!("Could not finish signing in: {e}");
            }
            return;
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_biometric::init())
        .plugin(privacy::init())
        .plugin(tauri_plugin_haptics::init())
        .plugin(apns::init())
        .plugin(live::init())
        .plugin(managed::init())
        .plugin(pin::init())
        .plugin(push::init())
        .plugin(share::init())
        .plugin(share::attach())
        .plugin(widget::init());
    // The camera scanner is a phone's; the same app on a laptop types the address.
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_barcode_scanner::init());
    builder
        .invoke_handler(tauri::generate_handler![
            server_url,
            mobile_settings,
            mobile_servers,
            oauth_verifier,
            bind_push_session,
            clear_push_session,
            open_mobile_settings,
            set_mobile_lock,
            forget_server,
            choose_server,
            startup_notice,
            pair_with,
            connect,
            unlock,
            take_activity_action,
            take_shared,
            attach_sheet,
            offer_recent_photo,
            live::show_activity,
            live::end_activity,
            widget::update_widget,
            pin::pin_shortcut,
            push::push_status,
            push::push_register,
            push::push_unregister,
            apns::apns_status,
            apns::apns_register,
            apns::apns_unregister
        ])
        .manage(PendingSignIn::default())
        .manage(SignInProof::default())
        .manage(Lock::default())
        .manage(navigation::Navigation::default())
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                if let Err(e) = window.state::<navigation::Navigation>().finish() {
                    eprintln!("Could not cancel navigation: {e}");
                }
            }
        })
        .setup(|app| {
            let handle = app.handle();
            app.manage(SettingsPath(resolve_settings_path(handle)?));
            // The organization's server: where the app opens before the person
            // has chosen one, and the only one it opens while it is locked.
            let policy = managed::load(handle, LAN_HTTP);
            let mut stored = settings(handle);
            stored.migrate();
            let server = policy.server_for(stored.server_url.as_ref());
            if server != stored.server_url {
                stored.server_url = server;
                save(handle, &stored)?;
            }
            app.manage(Managed(policy));
            let start = match stored.server_url {
                // The dashboard, not the root: the root sends everyone to the
                // sign-in form, and a session kept in the app's cookies would be
                // asked to sign in again on every launch.
                Some(server) => {
                    grant_console(handle, &server)?;
                    let destination = server.join("dashboard")?;
                    watch_navigation(handle, &destination)?;
                    WebviewUrl::External(destination)
                }
                None => WebviewUrl::App("index.html".into()),
            };
            open_window(handle, start)?;
            let links = handle.clone();
            app.deep_link()
                .on_open_url(move |event| on_deep_link(&links, event.urls()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building the AgenticOS app")
        .run(|app, event| {
            if let RunEvent::Ready | RunEvent::Resumed = event {
                let stored = settings(app);
                let enabled = lock_enabled(app, &stored) && stored.server_url.is_some();
                let unlocked_at = app
                    .state::<Lock>()
                    .0
                    .lock()
                    .ok()
                    .and_then(|lock| lock.unlocked_at);
                if should_lock(enabled, unlocked_at, Instant::now()) {
                    lock(app);
                }
            }
        });
}

#[cfg(test)]
mod tests {
    use std::time::{Duration, Instant};

    use agenticos_shell_core::{ActivityAction, Mode};

    use super::{shell_script, should_lock, take_asked, Asked, LockState, Settings, LOCK_AFTER};

    #[test]
    fn the_console_locks_on_first_open_and_after_a_while_away_only() {
        let now = Instant::now();
        assert!(should_lock(true, None, now));
        assert!(!should_lock(true, Some(now - Duration::from_secs(30)), now));
        assert!(should_lock(true, Some(now - LOCK_AFTER), now));
        assert!(!should_lock(false, None, now));
    }

    #[test]
    fn a_fresh_install_locks_by_default() {
        let settings: Settings = serde_json::from_str("{}").unwrap();
        assert!(settings.lock);
        assert!(settings.server_url.is_none());
    }

    #[test]
    fn a_decision_or_a_microphone_waits_for_the_lock_and_a_page_does_not() {
        let decide = || ActivityAction::Decide {
            approval_id: "ap1".into(),
            approved: true,
        };
        let mut state = LockState {
            locked: true,
            asked: Some(decide()),
            ..LockState::default()
        };
        assert_eq!(take_asked(&mut state), None);
        state.locked = false;
        assert_eq!(
            take_asked(&mut state),
            Some(Asked::Open {
                path: "/runs?tab=approvals".into(),
            })
        );
        assert_eq!(take_asked(&mut state), None, "taken once");

        state.locked = true;
        state.asked = Some(ActivityAction::Start(Mode::Dictate));
        assert_eq!(
            take_asked(&mut state),
            None,
            "no microphone behind the lock"
        );
        state.locked = false;
        assert_eq!(
            take_asked(&mut state),
            Some(Asked::Start { mode: "dictate" })
        );

        state.locked = true;
        state.asked = Some(ActivityAction::Open("/runs".into()));
        assert_eq!(
            take_asked(&mut state),
            Some(Asked::Open {
                path: "/runs".into()
            })
        );
    }

    #[test]
    fn the_shell_announces_itself_as_a_phone() {
        let script = shell_script("0.1.0");
        assert!(script.contains("__AGENTICOS_SHELL__"));
        assert!(script.contains("\"vibrancy\":false"));
        assert!(script.contains("\"window\":\"main\""));
    }
}
