//! Native consent to use the whole computer, for one conversation or one agent.
//!
//! A conversation's random grant is bound to the first conversation that uses
//! it (a draft has no server id yet). An agent's grant names the agent and holds
//! for every conversation with it, so the person is asked once per agent rather
//! than in every new chat. Each operation rechecks the saved grant and server.

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
    /// Set for consent given to one agent; it then binds no conversation.
    #[serde(default)]
    pub agent_id: Option<String>,
    #[serde(default)]
    pub agent_name: Option<String>,
}

#[derive(Serialize)]
pub struct Granted {
    id: String,
    path: String,
    agent_id: Option<String>,
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
pub async fn local_allow_computer(
    app: AppHandle,
    conversation_id: Option<String>,
    agent_id: Option<String>,
    agent_name: Option<String>,
) -> Result<Option<Granted>, String> {
    if let Some(id) = &conversation_id {
        uuid::Uuid::parse_str(id).map_err(|_| "Invalid conversation id.")?;
    }
    if let Some(id) = &agent_id {
        uuid::Uuid::parse_str(id).map_err(|_| "Invalid agent id.")?;
    }
    let server = origin(&app)?;
    let root = app
        .path()
        .home_dir()
        .map_err(|e| e.to_string())?
        .to_string_lossy()
        .into_owned();
    let (send, answer) = tokio::sync::oneshot::channel();
    let (message, allow) = consent_text(
        &server,
        agent_id
            .as_deref()
            .map(|_| agent_name.as_deref().unwrap_or("this agent")),
    );
    app.dialog()
        .message(message)
        .title("Allow whole-computer access?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(allow.into(), "Cancel".into()))
        .show(move |allowed| {
            let _ = send.send(allowed);
        });
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
        // An agent's consent spans its conversations, so it never binds one.
        conversation_id: if agent_id.is_some() { None } else { conversation_id },
        agent_id: agent_id.clone(),
        agent_name,
    });
    save(&path, &grants)?;
    Ok(Some(Granted {
        id,
        path: root,
        agent_id,
    }))
}

/// What the native dialog says, and its allow button: for this conversation, or
/// for every conversation with one named agent.
fn consent_text(server: &str, agent: Option<&str>) -> (String, &'static str) {
    match agent {
        Some(name) => (
            format!(
                "Allow {name} on {server} to read and change files anywhere your account can access, and run commands as you?\n\nCommands will run without individual native prompts. This is not a sandbox. Access is saved for {name} on this computer, in every conversation with it, until you revoke it in chat settings. macOS permissions still apply."
            ),
            "Allow for this agent",
        ),
        None => (
            format!(
                "Allow the agent in this conversation on {server} to read and change files anywhere your account can access, and run commands as you?\n\nCommands will run without individual native prompts. This is not a sandbox. Access is saved for this conversation until you revoke it in chat settings. macOS permissions still apply."
            ),
            "Allow for this conversation",
        ),
    }
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

fn authorize(
    grant: &mut Consent,
    server: &str,
    root: &str,
    conversation: &str,
    agent: Option<&str>,
) -> Result<(), String> {
    uuid::Uuid::parse_str(conversation).map_err(|_| "Invalid conversation id.")?;
    // The working directory is the home folder or a folder inside it: a coding
    // session may work in one project while the consent covers the computer.
    if grant.origin != server || !Path::new(root).starts_with(&grant.root) {
        return Err("This consent belongs to another server or working directory.".into());
    }
    if let Some(bound) = &grant.agent_id {
        return if agent == Some(bound.as_str()) {
            Ok(())
        } else {
            Err("This consent belongs to another agent.".into())
        };
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
    let agent = args.get("agent_id").and_then(Value::as_str);
    let unbound = grant.conversation_id.is_none() && grant.agent_id.is_none();
    authorize(grant, &server, root, conversation, agent)?;
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
            agent_id: None,
            agent_name: None,
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
            agent_id: None,
            agent_name: None,
        };
        let chat = uuid::Uuid::new_v4().to_string();
        assert!(authorize(&mut grant, "https://other.test", "/home/me", &chat, None).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/", &chat, None).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/home/me", "invalid", None).is_err());
        assert!(grant.conversation_id.is_none());
        authorize(&mut grant, "https://console.test", "/home/me", &chat, None).unwrap();
        let mut restored: Consent = serde_json::from_str(&serde_json::to_string(&grant).unwrap()).unwrap();
        authorize(&mut restored, "https://console.test", "/home/me", &chat, None).unwrap();
        assert!(authorize(
            &mut restored,
            "https://console.test",
            "/home/me",
            &uuid::Uuid::new_v4().to_string(),
            None
        )
        .is_err());
    }

    #[test]
    fn agent_consent_holds_in_every_conversation_with_that_agent_only() {
        let agent = uuid::Uuid::new_v4().to_string();
        let mut grant = Consent {
            id: "agent".into(),
            root: "/home/me".into(),
            origin: "https://console.test".into(),
            conversation_id: None,
            agent_id: Some(agent.clone()),
            agent_name: None,
        };
        for _ in 0..2 {
            let chat = uuid::Uuid::new_v4().to_string();
            authorize(&mut grant, "https://console.test", "/home/me", &chat, Some(&agent)).unwrap();
        }
        // It never binds the first conversation it was used in.
        assert!(grant.conversation_id.is_none());
        // A coding session may work in one project inside the home folder.
        let chat = uuid::Uuid::new_v4().to_string();
        authorize(&mut grant, "https://console.test", "/home/me/app", &chat, Some(&agent)).unwrap();
        let other = uuid::Uuid::new_v4().to_string();
        assert!(authorize(&mut grant, "https://console.test", "/home/me", &chat, Some(&other)).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/home/me", &chat, None).is_err());
        assert!(authorize(&mut grant, "https://console.test", "/home/mean", &chat, Some(&agent)).is_err());
    }

    #[test]
    fn a_consent_saved_before_agents_existed_still_reads_as_a_conversations() {
        let saved = r#"{"id":"old","root":"/home/me","origin":"https://console.test","conversation_id":null}"#;
        let consent: Consent = serde_json::from_str(saved).unwrap();
        assert!(consent.agent_id.is_none());
    }

    #[test]
    fn the_dialog_names_the_agent_it_asks_for() {
        let (message, allow) = consent_text("https://console.test", Some("AgenticOS"));
        assert!(message.contains("Allow AgenticOS on https://console.test"));
        assert!(message.contains("every conversation with it"));
        assert_eq!(allow, "Allow for this agent");
        let (_, allow) = consent_text("https://console.test", None);
        assert_eq!(allow, "Allow for this conversation");
    }
}
