//! A bounded, session-owned activity menu. It never executes a server operation itself.
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use tauri::{
    menu::{IsMenuItem, MenuItem, Submenu},
    AppHandle, Emitter, Manager, Wry,
};

#[derive(Clone, Deserialize, Serialize)]
pub struct Entry {
    id: String,
    title: String,
    path: String,
    /// Present only for a conversation whose originating socket is in this app.
    stop_conversation: Option<String>,
    #[serde(default)]
    question: bool,
}
#[derive(Default)]
pub struct Activity {
    entries: Mutex<std::collections::HashMap<String, Vec<Entry>>>,
    signature: Mutex<String>,
    conversations: Mutex<std::collections::HashMap<String, Option<String>>>,
}

fn validate(entries: &[Entry]) -> Result<(), String> {
    if entries.len() > 30 {
        return Err("Too many activity entries.".into());
    }
    for row in entries {
        uuid::Uuid::parse_str(&row.id).map_err(|_| "Invalid activity id.")?;
        if !crate::notify::is_console_path(&row.path) || row.path.len() > 512 || row.title.len() > 1024 {
            return Err("Invalid activity entry.".into());
        }
        if let Some(conversation) = &row.stop_conversation {
            uuid::Uuid::parse_str(conversation).map_err(|_| "Invalid conversation id.")?;
        }
    }
    Ok(())
}
#[tauri::command]
pub fn desktop_activity(
    app: AppHandle,
    webview: tauri::WebviewWindow,
    entries: Vec<Entry>,
    conversation_id: Option<String>,
    account_id: Option<String>,
    organization_id: Option<String>,
    origin: Option<String>,
) -> Result<(), String> {
    validate(&entries)?;
    if let Some(id) = &conversation_id {
        uuid::Uuid::parse_str(id).map_err(|_| "Invalid conversation id.")?;
    }
    let server_origin = crate::settings::current(&app)
        .server_url
        .map(|url| url.origin().ascii_serialization());
    if origin != server_origin {
        return Err("Activity belongs to another server.".into());
    }
    for value in [&account_id, &organization_id].into_iter().flatten() {
        uuid::Uuid::parse_str(value).map_err(|_| "Invalid account context.")?;
    }
    let source = webview.label();
    if source != crate::WINDOW && !crate::quick_ask::is_panel(source) {
        return Err("This window cannot publish activity.".into());
    }
    app.state::<Activity>()
        .conversations
        .lock()
        .map_err(|e| e.to_string())?
        .insert(source.to_owned(), conversation_id);
    let state = app.state::<Activity>();
    let fresh = {
        let mut sources = state.entries.lock().map_err(|e| e.to_string())?;
        let previous = sources.get(source);
        let fresh = entries
            .iter()
            .filter(|row| {
                row.question && !previous.is_some_and(|rows| rows.iter().any(|old| old.id == row.id && old.question))
            })
            .cloned()
            .collect::<Vec<_>>();
        sources.insert(source.to_owned(), entries);
        fresh
    };
    for row in fresh {
        if let (Some(account), Some(organization)) = (&account_id, &organization_id) {
            app.emit_to(crate::WINDOW, "desktop:question", serde_json::json!({ "account": account, "organization": organization, "title":row.title, "path":row.path })).map_err(|e| e.to_string())?;
        }
    }
    refresh(&app)
}
fn entries(app: &AppHandle) -> Vec<Entry> {
    let state = app.state::<Activity>();
    let sources = state.entries.lock().unwrap_or_else(|e| e.into_inner());
    let mut by_id = std::collections::BTreeMap::<String, Entry>::new();
    for rows in sources.values() {
        for row in rows {
            let current = by_id.entry(row.id.clone()).or_insert_with(|| row.clone());
            if row.stop_conversation.is_some() {
                current.stop_conversation = row.stop_conversation.clone();
            }
        }
    }
    by_id.into_values().take(30).collect()
}
fn label(value: &str) -> String {
    value.chars().filter(|c| !c.is_control()).take(80).collect()
}

pub fn menu(app: &AppHandle) -> tauri::Result<Submenu<Wry>> {
    let mut submenus = Vec::new();
    for row in entries(app) {
        let open = MenuItem::with_id(app, format!("activity:open:{}", row.id), "Open", true, None::<&str>)?;
        let stop = MenuItem::with_id(
            app,
            format!("activity:stop:{}", row.id),
            "Stop",
            row.stop_conversation.is_some(),
            None::<&str>,
        )?;
        submenus.push(Submenu::with_items(app, label(&row.title), true, &[&open, &stop])?);
    }
    let grants = crate::computer_access::active(app).unwrap_or_else(|error| {
        eprintln!("activity consents: {error}");
        Vec::new()
    });
    for grant in grants {
        let name = grant
            .conversation_id
            .as_deref()
            .map(|id| format!("Whole computer · {}", id.chars().take(8).collect::<String>()))
            .unwrap_or_else(|| "Whole computer · new chat".into());
        let revoke = MenuItem::with_id(
            app,
            format!("activity:revoke:{}", grant.id),
            "Revoke access",
            true,
            None::<&str>,
        )?;
        submenus.push(Submenu::with_items(app, name, true, &[&revoke])?);
    }
    let folders = crate::settings::current(app).local_grants;
    for grant in folders.iter().take(10) {
        let revoke = MenuItem::with_id(
            app,
            format!("activity:folder:{}", grant.path),
            "Revoke folder access",
            true,
            None::<&str>,
        )?;
        // The full path is the menu's label: never a shared project or agent grant.
        submenus.push(Submenu::with_items(app, label(&grant.path), true, &[&revoke])?);
    }
    let ready = MenuItem::with_id(app, "activity:readiness", "App readiness…", true, None::<&str>)?;
    let screen = MenuItem::with_id(
        app,
        "activity:screen",
        "Take back screen control",
        crate::screen::allowed(app),
        None::<&str>,
    )?;
    let mut items: Vec<&dyn IsMenuItem<Wry>> = vec![&ready, &screen];
    items.extend(submenus.iter().map(|item| item as &dyn IsMenuItem<Wry>));
    Submenu::with_items(app, "Activity & Access", true, &items)
}

pub fn refresh(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<Activity>();
    let signature = serde_json::to_string(&(
        entries(app),
        crate::computer_access::active(app)?,
        crate::settings::current(app).local_grants,
        crate::screen::allowed(app),
    ))
    .map_err(|e| e.to_string())?;
    let mut last = state.signature.lock().map_err(|e| e.to_string())?;
    if *last == signature {
        return Ok(());
    }
    // Keep old signature on failure so the next frame retries rebuilding the menu.
    let menu = app.state::<crate::ShellMenu>();
    if let Some(tray) = app.tray_by_id(crate::TRAY) {
        tray.set_menu(Some(menu.tray(app).map_err(|e| e.to_string())?))
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "macos")]
    app.set_menu(menu.menu_bar(app).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    *last = signature;
    Ok(())
}

pub fn handle(app: &AppHandle, id: &str) -> Result<(), String> {
    if id == "activity:readiness" {
        return crate::open_in_console_at(app, "/desktop/readiness");
    }
    if id == "activity:screen" {
        crate::screen::stop(app);
        return refresh(app);
    }
    if let Some(id) = id.strip_prefix("activity:revoke:") {
        crate::computer_access::local_revoke_computer(app.clone(), id.into())?;
        app.emit("desktop:access-changed", serde_json::json!({"kind":"computer","id":id}))
            .map_err(|e| e.to_string())?;
        return refresh(app);
    }
    if let Some(path) = id.strip_prefix("activity:folder:") {
        crate::local_work::local_revoke(app.clone(), path.to_owned())?;
        app.emit(
            "desktop:access-changed",
            serde_json::json!({"kind":"folder","path":path}),
        )
        .map_err(|e| e.to_string())?;
        return refresh(app);
    }
    for row in entries(app) {
        if id == format!("activity:open:{}", row.id) {
            return crate::open_in_console_at(app, &row.path);
        }
        if id == format!("activity:stop:{}", row.id) {
            if let Some(conversation) = row.stop_conversation {
                return app
                    .emit("desktop:stop-conversation", conversation)
                    .map_err(|e| e.to_string());
            }
        }
    }
    Ok(())
}
#[test]
fn activity_rejects_external_destinations_and_invalid_ids() {
    let mut entry = Entry {
        id: uuid::Uuid::new_v4().to_string(),
        title: "Working".into(),
        path: "/chat".into(),
        stop_conversation: None,
        question: false,
    };
    assert!(validate(&[entry.clone()]).is_ok());
    entry.path = "//outside.example".into();
    assert!(validate(&[entry.clone()]).is_err());
    entry.path = "/chat".into();
    entry.stop_conversation = Some("bad".into());
    assert!(validate(&[entry]).is_err());
}

pub fn conversation(app: &AppHandle, label: &str) -> Option<String> {
    app.state::<Activity>()
        .conversations
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(label)
        .cloned()
        .flatten()
}

pub fn remove_source(app: &AppHandle, source: &str) -> Result<(), String> {
    let state = app.state::<Activity>();
    state.entries.lock().map_err(|e| e.to_string())?.remove(source);
    state.conversations.lock().map_err(|e| e.to_string())?.remove(source);
    refresh(app)
}
