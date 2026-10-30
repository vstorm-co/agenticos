//! Isolated native-engine check: no device connection, model, personal browser or saved app state.
#[path = "../src/native_browser.rs"]
mod native_browser;
const WINDOW: &str = "main";

#[tauri::command]
fn device_status() -> String {
    "privileged-console-marker".to_owned()
}

use serde_json::{json, Map, Value};
use std::io::{Read, Write};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

async fn verify(app: &tauri::AppHandle, address: &str) -> Result<(), String> {
    eprintln!("native smoke: create");
    let opened = native_browser::create(
        app,
        0,
        Some("a".repeat(64)),
        Some("a".repeat(64)),
        Some(vec!["127.0.0.1".into()]),
        address,
    )
    .await?;
    let id = opened.get("id").and_then(Value::as_str).ok_or("Missing native tab")?;
    let lease = opened.get("lease").and_then(Value::as_str).ok_or("Missing lease")?;
    // WebKitGTK hit-testing requires a mapped WebView, as in the real console.
    native_browser::native_browser_view(
        app.clone(),
        app.get_webview(WINDOW).ok_or("Console missing")?,
        id.to_owned(),
        "show".into(),
        Some(serde_json::from_value(json!({"x":0,"y":80,"width":1000,"height":650})).map_err(|e| e.to_string())?),
        None,
        Some("smoke-renderer".into()),
    )
    .await?;
    let call = |method: &str, params: Value| -> Map<String, Value> {
        json!({"id":id,"lease":lease,"method":method,"params":params})
            .as_object()
            .unwrap()
            .clone()
    };
    let original = native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"String(performance.timeOrigin)"}),
        ),
    )
    .await?;
    eprintln!("native smoke: navigate");
    native_browser::run(app, "browser.command", &call("Page.navigate", json!({"url":address}))).await?;
    eprintln!("native smoke: wait for document");
    for _ in 0..100 {
        if let Ok(result) = native_browser::run(
            app,
            "browser.command",
            &call(
                "Runtime.evaluate",
                json!({"expression":"({document:String(performance.timeOrigin),title:document.readyState === 'complete' ? document.title : ''})"}),
            ),
        )
        .await
        {
            if result["result"]["value"]["title"] == "Native fixture"
                && result["result"]["value"]["document"] != original["result"]["value"]
            {
                break;
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
    eprintln!("native smoke: redirect");
    native_browser::run(
        app,
        "browser.command",
        &call("Page.navigate", json!({"url":format!("{address}redirect")})),
    )
    .await?;
    for _ in 0..100 {
        let location = native_browser::run(
            app,
            "browser.command",
            &call("Runtime.evaluate", json!({"expression":"location.pathname"})),
        )
        .await;
        if matches!(location, Ok(ref reply) if reply["result"]["value"] == "/after-redirect") {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
    let control = native_browser::run(
        app,
        "browser.control",
        &json!({"id":id,"lease":lease}).as_object().unwrap().clone(),
    )
    .await?;
    if control["held"] != false {
        return Err("A server redirect incorrectly took control from the agent".into());
    }
    eprintln!("native smoke: promise");
    let answer = native_browser::run(app,"browser.command",&call("Runtime.evaluate",json!({"expression":"new Promise(resolve=>setTimeout(()=>resolve(document.querySelector('button').textContent),80))"}))).await?;
    if answer["result"]["value"] != "Open" {
        return Err(format!("Native promise failed: {answer:?}"));
    }
    eprintln!("native smoke: click");
    native_browser::run(
        app,
        "browser.command",
        &call(
            "Input.dispatchMouseEvent",
            json!({"type":"mouseReleased","x":40,"y":20}),
        ),
    )
    .await?;
    let answer = native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"document.querySelector('output').textContent"}),
        ),
    )
    .await?;
    if answer["result"]["value"] != "clicked" {
        return Err(format!("Native click failed: {answer:?}"));
    }
    eprintln!("native smoke: text input");
    native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"document.querySelector('input').focus()"}),
        ),
    )
    .await?;
    native_browser::run(
        app,
        "browser.command",
        &call("Input.insertText", json!({"text":"native input"})),
    )
    .await?;
    let typed = native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"document.querySelector('input').value"}),
        ),
    )
    .await?;
    if typed["result"]["value"] != "native input" {
        return Err("Native text input failed".into());
    }
    let control = native_browser::run(
        app,
        "browser.control",
        &json!({"id":id,"lease":lease}).as_object().unwrap().clone(),
    )
    .await?;
    if control["held"] != false {
        return Err("Agent text input incorrectly took over its own tab".into());
    }
    eprintln!("native smoke: page capabilities");
    let refusal = native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"window.__TAURI_INTERNALS__.invoke('device_status').then(()=>false,()=>true)"}),
        ),
    )
    .await?;
    if refusal["result"]["value"] != true {
        return Err("A child page inherited console permissions".into());
    }
    native_browser::run(
        app,
        "browser.command",
        &call(
            "Runtime.evaluate",
            json!({"expression":"window.__TAURI_INTERNALS__.invoke('native_browser_input')"}),
        ),
    )
    .await?;
    let status = native_browser::run(
        app,
        "browser.control",
        &json!({"id":id,"lease":lease}).as_object().unwrap().clone(),
    )
    .await?;
    if status["held"] != true {
        return Err("The page's one-way takeover notification was not accepted".into());
    }
    eprintln!("native smoke: takeover");
    let held: Map<String, Value> = json!({"id":id,"lease":lease,"held":true}).as_object().unwrap().clone();
    native_browser::run(app, "browser.control", &held).await?;
    if native_browser::run(
        app,
        "browser.command",
        &call(
            "Input.dispatchMouseEvent",
            json!({"type":"mouseReleased","x":40,"y":20}),
        ),
    )
    .await
    .is_ok()
    {
        return Err("A held native tab accepted agent input".into());
    }
    eprintln!("native smoke: release");
    let release: Map<String, Value> = json!({"id":id,"lease":lease}).as_object().unwrap().clone();
    native_browser::run(app, "browser.release", &release).await?;
    let reopen: Map<String, Value> = json!({"scope":"a".repeat(64),"allowed_domains":["127.0.0.1"],"resume":true})
        .as_object()
        .unwrap()
        .clone();
    let resumed = native_browser::open(app, &reopen).await?;
    if resumed["id"] != id || resumed["lease"] == lease || resumed["reused"] != true {
        return Err("The conversation tab was not resumed with a new lease".into());
    }
    if native_browser::open(app, &reopen).await.is_ok() {
        return Err("A second run leased the busy tab".into());
    }
    if native_browser::run(
        app,
        "browser.command",
        &call("Runtime.evaluate", json!({"expression":"1"})),
    )
    .await
    .is_ok()
    {
        return Err("An expired lease could operate the tab".into());
    }
    native_browser::run(
        app,
        "browser.control",
        &json!({"id":id,"lease":resumed["lease"],"held":false})
            .as_object()
            .unwrap()
            .clone(),
    )
    .await?;
    native_browser::run(
        app,
        "browser.heartbeat",
        &json!({"id":id,"lease":resumed["lease"]}).as_object().unwrap().clone(),
    )
    .await?;
    let invalid = call("Page.navigate", json!({"url":"https://outside.example/"}));
    let mut invalid = invalid;
    invalid.insert("lease".into(), resumed["lease"].clone());
    let refusal = native_browser::run(app, "browser.command", &invalid).await.unwrap_err();
    if !refusal.contains("outside the agent's allowed domains") {
        return Err(format!("Native domain policy did not reject navigation: {refusal}"));
    }
    eprintln!("native smoke: renderer ownership");
    let console = app.get_webview(WINDOW).ok_or("Missing console")?;
    for mount in ["old-mount", "new-mount"] {
        native_browser::native_browser_view(
            app.clone(),
            console.clone(),
            id.into(),
            "show".into(),
            Some(serde_json::from_value(json!({"x":0,"y":80,"width":900,"height":600})).unwrap()),
            None,
            Some(mount.into()),
        )
        .await?;
    }
    native_browser::native_browser_view(
        app.clone(),
        console.clone(),
        id.into(),
        "hide".into(),
        None,
        None,
        Some("old-mount".into()),
    )
    .await?;
    if !native_browser::handle_menu(app, "back")? {
        return Err("An obsolete renderer hid the current mount".into());
    }
    native_browser::native_browser_view(
        app.clone(),
        console,
        id.into(),
        "hide".into(),
        None,
        None,
        Some("new-mount".into()),
    )
    .await?;
    native_browser::hide_all(app);
    if native_browser::handle_menu(app, "reload")? {
        return Err("A hidden native tab captured the console menu".into());
    }
    native_browser::run(
        app,
        "browser.release",
        &json!({"id":id,"lease":resumed["lease"],"close":true})
            .as_object()
            .unwrap()
            .clone(),
    )
    .await?;
    if app.get_webview(id).is_some() {
        return Err("An explicitly closed native tab survived release".into());
    }
    native_browser::close_all(app).await;
    if app.get_webview(id).is_some() {
        return Err("The native tab survived disconnect cleanup".into());
    }
    println!("NATIVE_BROWSER_SMOKE_OK: promise, click, takeover, conversation resume, lease exclusion, stale lease, domains, cleanup");
    Ok(())
}

fn main() {
    let server = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = format!("http://{}/", server.local_addr().unwrap());
    std::thread::spawn(move || {
        for mut connection in server.incoming().flatten() {
            let mut request = [0; 4096];
            let _ = connection.read(&mut request);
            if std::str::from_utf8(&request)
                .unwrap_or("")
                .starts_with("GET /redirect ")
            {
                let _ = write!(
                    connection,
                    "HTTP/1.1 302 Found\r\nLocation: /after-redirect\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                );
                continue;
            }
            let javascript = std::str::from_utf8(&request).unwrap_or("").starts_with("GET /app.js");
            let body = if javascript {
                "document.querySelector('button').onclick=()=>document.querySelector('output').textContent='clicked';"
            } else {
                "<!doctype html><title>Native fixture</title><button>Open</button><input aria-label='Name'><output></output><script src='/app.js'></script>"
            };
            let content_type = if javascript { "text/javascript" } else { "text/html" };
            let _ = write!(
                connection,
                "HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Security-Policy: default-src 'self'; script-src 'self'; connect-src 'self'\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
        }
    });
    tauri::Builder::default()
        .manage(native_browser::NativeBrowsers::default())
        .invoke_handler(tauri::generate_handler![
            native_browser::native_browser_view,
            native_browser::native_browser_input,
            device_status
        ])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::External("about:blank".parse()?))
                .visible(cfg!(target_os = "linux"))
                .inner_size(1100.0, 800.0)
                .build()?;
            app.add_capability(
                tauri::ipc::CapabilityBuilder::new("smoke-console")
                    .local(false)
                    .remote("http://*:*/*".into())
                    .webview("main")
                    .permission("allow-device-status"),
            )?;
            let app = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let result = verify(&app, &address).await;
                if let Err(error) = &result {
                    eprintln!("NATIVE_BROWSER_SMOKE_FAILED: {error}");
                    native_browser::close_all(&app).await;
                }
                app.exit(if result.is_ok() { 0 } else { 1 });
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("isolated native browser app");
}
