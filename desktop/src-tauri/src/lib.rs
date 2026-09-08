//! A window around a deployment's console.
//!
//! The console itself stays on the server: this shell holds one setting, the
//! address of that server, and points its webview at it. The first launch, and
//! "Change server…" afterwards, show a local page asking for the address;
//! everything after that is the same Next.js application a browser would load,
//! with the same cookies, the same permissions and the same tenant checks.

use std::fs;
use std::io::ErrorKind;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};
use tauri::menu::{Menu, MenuItem, Submenu};
use tauri::{AppHandle, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder};

const WINDOW: &str = "main";
const CHANGE_SERVER: &str = "change-server";
const RELOAD: &str = "reload";

#[derive(Serialize, Deserialize)]
struct Settings {
    server_url: Url,
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("No configuration directory for this account: {e}"))?;
    Ok(dir.join("server.json"))
}

fn stored_server(app: &AppHandle) -> Result<Option<Url>, String> {
    let path = settings_path(app)?;
    let raw = match fs::read_to_string(&path) {
        Ok(raw) => raw,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(None),
        Err(e) => return Err(format!("Cannot read {}: {e}", path.display())),
    };
    let settings: Settings =
        serde_json::from_str(&raw).map_err(|e| format!("{} is not a saved server address: {e}", path.display()))?;
    Ok(Some(settings.server_url))
}

fn store_server(app: &AppHandle, server_url: Url) -> Result<(), String> {
    let path = settings_path(app)?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("Cannot create {}: {e}", dir.display()))?;
    }
    let raw = serde_json::to_string_pretty(&Settings { server_url }).map_err(|e| e.to_string())?;
    fs::write(&path, raw).map_err(|e| format!("Cannot write {}: {e}", path.display()))
}

/// The address a person typed, as the URL the webview will be pointed at.
///
/// A bare host is the common spelling (`agenticos.acme.com`), so a missing scheme
/// means `https`. Anything that is not a web address is refused here rather than
/// handed to the webview, which would show a platform error page with no way back
/// except the menu.
fn parse_server_url(typed: &str) -> Result<Url, String> {
    let typed = typed.trim();
    if typed.is_empty() {
        return Err("Enter the address of your AgenticOS server.".to_owned());
    }
    let spelled = if typed.contains("://") {
        typed.to_owned()
    } else {
        format!("https://{typed}")
    };
    let url = Url::parse(&spelled).map_err(|_| format!("{typed} is not a web address."))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(format!(
            "{typed} is not a web address: the shell opens http and https servers."
        ));
    }
    if url.host_str().is_none() {
        return Err(format!("{typed} names no host."));
    }
    Ok(url)
}

/// Where the shell's own page lives inside the webview.
///
/// Tauri serves the local `frontendDist` from a custom scheme on macOS and Linux
/// and from a loopback name on Windows, where WebView2 has no custom schemes.
fn connect_page() -> Url {
    let origin = if cfg!(windows) {
        "http://tauri.localhost"
    } else {
        "tauri://localhost"
    };
    Url::parse(&format!("{origin}/index.html")).expect("a literal origin parses")
}

#[tauri::command]
fn server_url(app: AppHandle) -> Result<Option<Url>, String> {
    stored_server(&app)
}

#[tauri::command]
fn connect(app: AppHandle, window: WebviewWindow, url: String) -> Result<(), String> {
    let server = parse_server_url(&url)?;
    store_server(&app, server.clone())?;
    window.navigate(server).map_err(|e| e.to_string())
}

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    WebviewWindowBuilder::new(app, WINDOW, url)
        .title("AgenticOS")
        .inner_size(1280.0, 800.0)
        .min_inner_size(900.0, 600.0)
        .build()
}

fn install_menu(app: &AppHandle) -> tauri::Result<()> {
    let change_server = MenuItem::with_id(app, CHANGE_SERVER, "Change server…", true, None::<&str>)?;
    let reload = MenuItem::with_id(app, RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?;
    let server = Submenu::with_items(app, "Server", true, &[&change_server, &reload])?;
    let menu = Menu::default(app)?;
    menu.insert(&server, 1)?;
    app.set_menu(menu)?;
    app.on_menu_event(|app, event| {
        let Some(window) = app.get_webview_window(WINDOW) else {
            return;
        };
        let outcome = match event.id().as_ref() {
            CHANGE_SERVER => window.navigate(connect_page()),
            RELOAD => window.eval("location.reload()"),
            _ => Ok(()),
        };
        if let Err(e) = outcome {
            eprintln!("menu action {} failed: {e}", event.id().as_ref());
        }
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![server_url, connect])
        .setup(|app| {
            let handle = app.handle();
            install_menu(handle)?;
            let start = match stored_server(handle) {
                Ok(Some(server)) => WebviewUrl::External(server),
                Ok(None) => WebviewUrl::App("index.html".into()),
                Err(e) => {
                    eprintln!("{e}");
                    WebviewUrl::App("index.html".into())
                }
            };
            open_window(handle, start)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::parse_server_url;

    #[test]
    fn a_bare_host_is_opened_over_https() {
        assert_eq!(
            parse_server_url("agenticos.acme.com").unwrap().as_str(),
            "https://agenticos.acme.com/"
        );
    }

    #[test]
    fn a_scheme_and_port_are_kept_as_typed() {
        assert_eq!(
            parse_server_url(" http://localhost:3000 ").unwrap().as_str(),
            "http://localhost:3000/"
        );
    }

    #[test]
    fn an_empty_address_is_refused() {
        assert!(parse_server_url("   ").is_err());
    }

    #[test]
    fn a_scheme_the_webview_cannot_open_is_refused() {
        assert!(parse_server_url("ftp://files.acme.com").is_err());
    }

    #[test]
    fn a_scheme_with_no_host_is_refused() {
        assert!(parse_server_url("https://").is_err());
    }
}
