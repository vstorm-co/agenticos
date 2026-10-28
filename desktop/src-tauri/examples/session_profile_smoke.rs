//! Run `write`, then `read` as separate processes; no real account or permission prompts.
#[path = "../src/webview_profile.rs"]
mod webview_profile;

use std::time::Duration;
use tauri::webview::Cookie;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const COOKIE: &str = "agenticos_session_smoke";
const ADDRESS: &str = "https://session-smoke.invalid/";

async fn verify(app: &tauri::AppHandle, write: bool) -> Result<(), String> {
    let main = app.get_webview_window("main").ok_or("main window missing")?;
    if write {
        main.set_cookie(
            Cookie::parse(format!(
                "{COOKIE}=fixture; Domain=session-smoke.invalid; Path=/; Max-Age=600; HttpOnly; SameSite=Lax"
            ))
            .map_err(|e| e.to_string())?
            .into_owned(),
        )
        .map_err(|e| e.to_string())?;
    }
    for label in ["main", "blobby", "quick-ask"] {
        let window = app.get_webview_window(label).ok_or("companion missing")?;
        let mut found = false;
        for _ in 0..100 {
            let cookies = window
                .cookies_for_url(ADDRESS.parse().unwrap())
                .map_err(|e| e.to_string())?;
            if cookies
                .iter()
                .any(|cookie| cookie.name() == COOKIE && cookie.http_only() == Some(true))
            {
                found = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
        if !found {
            return Err(format!("{label}: persistent HttpOnly cookie missing"));
        }
    }
    let private = app.get_webview_window("private").ok_or("private window missing")?;
    if private
        .cookies_for_url(ADDRESS.parse().unwrap())
        .map_err(|e| e.to_string())?
        .iter()
        .any(|cookie| cookie.name() == COOKIE)
    {
        return Err("Private agent browsing inherited the console session".into());
    }
    if write {
        // Let WebKit finish its asynchronous disk write before the process exits.
        tokio::time::sleep(Duration::from_secs(2)).await;
    } else {
        main.delete_cookie(
            Cookie::build((COOKIE, ""))
                .domain("session-smoke.invalid")
                .path("/")
                .build(),
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn main() {
    let mode = std::env::args().nth(1).expect("write or read");
    assert!(matches!(mode.as_str(), "write" | "read"));
    tauri::Builder::default()
        .setup(move |app| {
            for label in ["main", "blobby", "quick-ask"] {
                webview_profile::window(app, label, WebviewUrl::External("about:blank".parse()?))?
                    .visible(false)
                    .build()?;
            }
            WebviewWindowBuilder::new(app, "private", WebviewUrl::External("about:blank".parse()?))
                .incognito(true)
                .visible(false)
                .build()?;
            let app = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let result = verify(&app, mode == "write").await;
                match &result {
                    Ok(()) => eprintln!("SESSION_PROFILE_SMOKE_OK"),
                    Err(error) => eprintln!("SESSION_PROFILE_SMOKE_FAILED: {error}"),
                }
                app.exit(if result.is_ok() { 0 } else { 1 });
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("session profile fixture");
}
