//! AgenticOS on a phone: the deployment's console in a full-screen webview,
//! reached by scanning the QR the console shows (#2097).
//!
//! Like the desktop shell it holds one thing of its own - the server's address -
//! and is otherwise the console the server serves, with its cookies and its
//! permissions. Its own pages are only the first run: scan a code, or type an
//! address. What makes a sign-in this app's and nobody else's is shared with the
//! desktop shell, in `agenticos-shell-core`.
//!
//! The console is locked behind Face ID, Touch ID or the device's fingerprint
//! when the app comes back to the front after a while away.

use std::fs;
use std::io::ErrorKind;
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use agenticos_shell_core::{
    deep_link_return, external_sign_in_url, is_oauth_start, mint_nonce, pairing_link,
    parse_server_url_with, Pairing, PendingSignIn,
};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, RunEvent, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};
use tauri_plugin_biometric::{AuthOptions, BiometricExt};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_opener::OpenerExt;

const WINDOW: &str = "main";
/// After this long away, the console is locked again when the app returns.
const LOCK_AFTER: Duration = Duration::from_secs(5 * 60);
/// Plain `http` to the laptop beside the phone, in a development build only.
const LAN_HTTP: bool = cfg!(debug_assertions);

#[derive(Serialize, Deserialize, Default)]
struct Settings {
    #[serde(default)]
    server_url: Option<Url>,
    /// Lock the console behind the device's biometrics. On unless turned off.
    #[serde(default = "locked_by_default")]
    lock: bool,
}

fn locked_by_default() -> bool {
    true
}

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

/// When the console was last unlocked, and whether it is locked now.
#[derive(Default)]
struct Lock(Mutex<LockState>);

#[derive(Default)]
struct LockState {
    unlocked_at: Option<Instant>,
    locked: bool,
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

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    let handle = app.clone();
    let version = app.package_info().version.to_string();
    WebviewWindowBuilder::new(app, WINDOW, url)
        .initialization_script(shell_script(&version))
        // The one navigation the webview refuses: a provider sign-in, handed to
        // the system browser and returned by deep link, as on the desktop (#1532).
        .on_navigation(move |url| {
            let server = settings(&handle).server_url;
            if !is_oauth_start(server.as_ref(), url) {
                return true;
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

/// The console - a remote page - may ask for one thing: the unlock prompt again.
/// Granted for the configured server's origin only, as the desktop shell grants
/// its console's commands.
fn grant_unlock(app: &AppHandle, server: &Url) -> Result<(), String> {
    let pattern = format!("{}/*", server.origin().ascii_serialization());
    app.add_capability(
        tauri::ipc::CapabilityBuilder::new(format!("console-unlock-{pattern}"))
            .remote(pattern)
            .local(false)
            .window(WINDOW)
            .permission("allow-unlock"),
    )
    .map_err(|e| e.to_string())
}

fn console(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window(WINDOW)
        .ok_or_else(|| "The app has no window.".to_owned())
}

/// Sign in with a scanned code: remember its console and send the webview to redeem it.
fn pair(app: &AppHandle, pairing: &Pairing) -> Result<(), String> {
    grant_unlock(app, &pairing.server)?;
    let mut stored = settings(app);
    stored.server_url = Some(pairing.server.clone());
    save(app, &stored)?;
    console(app)?
        .navigate(pairing.redeem_url())
        .map_err(|e| e.to_string())
}

/// What the onboarding page shows first: an address already chosen, if any.
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
fn connect(app: AppHandle, url: String) -> Result<(), String> {
    let server = parse_server_url_with(&url, LAN_HTTP)?;
    grant_unlock(&app, &server)?;
    let mut stored = settings(&app);
    stored.server_url = Some(server.clone());
    save(&app, &stored)?;
    let login = server.join("login").map_err(|e| e.to_string())?;
    console(&app)?.navigate(login).map_err(|e| e.to_string())
}

/// Hide the console and ask for the device's biometrics; reveal it once they answer.
///
/// A phone with no biometrics enrolled falls back to its passcode
/// (`allow_device_credential`). One with neither is not locked: a lock nobody
/// can open is a broken app, not a safe one.
fn lock(app: &AppHandle) {
    let available = app
        .biometric()
        .status()
        .map(|status| status.is_available)
        .unwrap_or(false);
    if !available {
        return;
    }
    let Ok(window) = console(app) else { return };
    if let Ok(mut lock) = app.state::<Lock>().0.lock() {
        lock.locked = true;
    }
    if let Err(e) = window.eval(LOCK_SCRIPT) {
        eprintln!("lock: {e}");
    }
    ask_to_unlock(app);
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

/// Whether coming back to the front should lock: long enough since the last unlock.
fn should_lock(lock_enabled: bool, unlocked_at: Option<Instant>, now: Instant) -> bool {
    lock_enabled && unlocked_at.map_or(true, |at| now.duration_since(at) >= LOCK_AFTER)
}

fn on_deep_link(app: &AppHandle, links: Vec<Url>) {
    let stored = settings(app);
    let expected = app
        .state::<PendingSignIn>()
        .0
        .lock()
        .ok()
        .and_then(|mut slot| slot.take());
    for link in links {
        if let Ok(pairing) = pairing_link(link.as_str(), LAN_HTTP) {
            if let Err(e) = pair(app, &pairing) {
                eprintln!("pair: {e}");
            }
            return;
        }
        if let Some(destination) = deep_link_return(
            stored.server_url.as_ref(),
            expected.as_deref(),
            link.as_str(),
        ) {
            if let Ok(window) = console(app) {
                if let Err(e) = window.navigate(destination) {
                    eprintln!("Could not finish signing in: {e}");
                }
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
        .plugin(tauri_plugin_biometric::init());
    // The camera scanner is a phone's; the same app on a laptop types the address.
    #[cfg(mobile)]
    let builder = builder.plugin(tauri_plugin_barcode_scanner::init());
    builder
        .invoke_handler(tauri::generate_handler![
            server_url, pair_with, connect, unlock
        ])
        .manage(PendingSignIn::default())
        .manage(Lock::default())
        .setup(|app| {
            let handle = app.handle();
            app.manage(SettingsPath(resolve_settings_path(handle)?));
            let start = match settings(handle).server_url {
                // The dashboard, not the root: the root sends everyone to the
                // sign-in form, and a session kept in the app's cookies would be
                // asked to sign in again on every launch.
                Some(server) => {
                    grant_unlock(handle, &server)?;
                    WebviewUrl::External(server.join("dashboard")?)
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
                let enabled = stored.lock && stored.server_url.is_some();
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

    use super::{shell_script, should_lock, Settings, LOCK_AFTER};

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
    fn the_shell_announces_itself_as_a_phone() {
        let script = shell_script("0.1.0");
        assert!(script.contains("__AGENTICOS_SHELL__"));
        assert!(script.contains("\"vibrancy\":false"));
        assert!(script.contains("\"window\":\"main\""));
    }
}
