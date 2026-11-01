//! Native consent for one conversation to use the whole computer.
//!
//! The random grant is bound to the first conversation that uses it (a draft
//! has no server id yet). Each operation rechecks the saved grant and server.

use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::settings;

#[derive(Default)]
pub struct Access(Mutex<()>);

#[derive(Clone, Serialize, Deserialize)]
pub struct Consent {
    pub id: String,
    pub root: String,
    pub origin: String,
    pub conversation_id: Option<String>,
}

#[derive(Serialize)]
pub struct Granted {
    id: String,
    path: String,
}

fn store(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join("computer-access.json"))
        .map_err(|e| e.to_string())
}

fn load(path: &Path) -> Result<Vec<Consent>, String> {
    match std::fs::read(path) {
        Ok(bytes) => serde_json::from_slice(&bytes).map_err(|e| format!("Cannot read computer consents: {e}")),
        Err(error) if error.kind() == ErrorKind::NotFound => Ok(Vec::new()),
        Err(error) => Err(format!("Cannot read computer consents: {error}")),
    }
}

fn save(path: &Path, grants: &[Consent]) -> Result<(), String> {
    let bytes = serde_json::to_vec(grants).map_err(|e| e.to_string())?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let pending = path.with_extension("pending");
    std::fs::write(&pending, bytes).map_err(|e| e.to_string())?;
    std::fs::rename(pending, path).map_err(|e| e.to_string())
}

pub fn active(app: &AppHandle) -> Result<Vec<Consent>, String> {
    let server = crate::settings::current(app)
        .server_url
        .map(|url| url.origin().ascii_serialization());
    Ok(load(&store(app)?)?
        .into_iter()
        .filter(|grant| Some(&grant.origin) == server.as_ref())
        .collect())
}

fn origin(app: &AppHandle) -> Result<String, String> {
    settings::current(app)
        .server_url
        .map(|url| url.origin().ascii_serialization())
        .ok_or_else(|| "Connect to a server first.".to_string())
}

#[tauri::command]
pub async fn local_allow_computer(app: AppHandle, conversation_id: Option<String>) -> Result<Option<Granted>, String> {
    if let Some(id) = &conversation_id {
        uuid::Uuid::parse_str(id).map_err(|_| "Invalid conversation id.")?;
    }
    let server = origin(&app)?;
    let root = app
        .path()
        .home_dir()
        .map_err(|e| e.to_string())?
        .to_string_lossy()
        .into_owned();
    let (send, answer) = tokio::sync::oneshot::channel();
    app.dialog().message(format!(
        "Allow the agent in this conversation on {server} to read and change files anywhere your account can access, and run commands as you?\n\nCommands will run without individual native prompts. This is not a sandbox. Access is saved for this conversation until you revoke it in chat settings. macOS permissions still apply."
    )).title("Allow whole-computer access?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Allow for this conversation".into(), "Cancel".into()))
        .show(move |allowed| { let _ = send.send(allowed); });
    if !answer.await.unwrap_or(false) {
        return Ok(None);
    }
    if origin(&app)? != server {
        return Err("The server changed. Choose access again.".into());
    }
    let id = uuid::Uuid::new_v4().to_string();
    let state = app.state::<Access>();
    let _guard = state.0.lock().map_err(|e| e.to_string())?;
    let path = store(&app)?;
    let mut grants = load(&path)?;
    grants.push(Consent {
        id: id.clone(),
        root: root.clone(),
        origin: server,
        conversation_id,
    });
    save(&path, &grants)?;
    Ok(Some(Granted { id, path: root }))
}

/// Connection changes cannot carry another account's conversation consents.
pub fn clear(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state.0.lock().map_err(|e| e.to_string())?;
    save(&store(app)?, &[])
}

#[tauri::command]
pub fn local_revoke_computer(app: AppHandle, id: String) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state.0.lock().map_err(|e| e.to_string())?;
    let path = store(&app)?;
    let mut grants = load(&path)?;
    grants.retain(|grant| grant.id != id);
    save(&path, &grants)?;
    Ok(())
}

fn authorize(grant: &mut Consent, server: &str, root: &str, conversation: &str) -> Result<(), String> {
    uuid::Uuid::parse_str(conversation).map_err(|_| "Invalid conversation id.")?;
    if grant.origin != server || grant.root != root {
        return Err("This consent belongs to another server or working directory.".into());
    }
    if let Some(bound) = &grant.conversation_id {
        if bound != conversation {
            return Err("This consent belongs to another conversation.".into());
        }
    } else {
        grant.conversation_id = Some(conversation.to_owned());
    }
    Ok(())
}

pub fn check(app: &AppHandle, args: &Map<String, Value>) -> Result<(), String> {
    let string = |key| {
        args.get(key)
            .and_then(Value::as_str)
            .ok_or_else(|| format!("Missing {key}."))
    };
    let id = string("computer_grant")?;
    let root = string("root")?;
    let conversation = string("conversation_id")?;
    if string("mode")? != "full_access" {
        return Err("Whole-computer access requires full access.".into());
    }
    let server = origin(app)?;
    let state = app.state::<Access>();
    let _guard = state.0.lock().map_err(|e| e.to_string())?;
    let path = store(app)?;
    let mut saved = load(&path)?;
    let grant = saved
        .iter_mut()
        .find(|grant| grant.id == id)
        .ok_or_else(|| "Whole-computer access was not granted or has been revoked.".to_string())?;
    let unbound = grant.conversation_id.is_none();
    authorize(grant, &server, root, conversation)?;
    if unbound {
        save(&path, &saved)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn consents_persist_and_revocation_survives_restart() {
        let folder = std::env::temp_dir().join(format!("agenticos-consents-{}", uuid::Uuid::new_v4()));
        let path = folder.join("consents.json");
        assert!(load(&path).unwrap().is_empty());
        let grant = Consent {
            id: "granted".into(),
            root: "/home/me".into(),
            origin: "https://console.test".into(),
            conversation_id: Some(uuid::Uuid::new_v4().to_string()),
        };
        save(&path, &[grant]).unwrap();
        let mut restored = load(&path).unwrap();
        assert_eq!(restored.len(), 1);
        restored.retain(|grant| grant.id != "granted");
        save(&path, &restored).unwrap();
        assert!(load(&path).unwrap().is_empty());
        std::fs::write(&path, "broken").unwrap();
        assert!(load(&path).is_err());
        std::fs::remove_dir_all(folder).unwrap();
    }

    #[test]
    fn draft_consent_binds_once_and_survives_serialization() {
        let mut grant = Consent {
            id: "secret".into(),
            root: "/home/me".into(),
            origin: "https://console.test".into(),
            conversation_id: None,
        };
        let chat = uuid::Uuid::new_v4().to_string();
        assert!(authorize(&mut grant, "https://other.test", "/home/me", &chat).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/", &chat).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/home/me", "invalid").is_err());
        assert!(grant.conversation_id.is_none());
        authorize(&mut grant, "https://console.test", "/home/me", &chat).unwrap();
        let mut restored: Consent = serde_json::from_str(&serde_json::to_string(&grant).unwrap()).unwrap();
        authorize(&mut restored, "https://console.test", "/home/me", &chat).unwrap();
        assert!(authorize(
            &mut restored,
            "https://console.test",
            "/home/me",
            &uuid::Uuid::new_v4().to_string()
        )
        .is_err());
    }
}
