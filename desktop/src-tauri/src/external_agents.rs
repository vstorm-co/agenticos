//! Device-owned ACP commands. The server can select an ID, never supply a command.

use std::path::Path;

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::settings;

#[derive(Clone, Copy, Debug, Default, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Provider {
    #[default]
    Custom,
    Antigravity,
    #[serde(rename = "opencode")]
    OpenCode,
    #[serde(rename = "opencode_go")]
    OpenCodeGo,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Registration {
    #[serde(default)]
    pub provider: Provider,
    pub id: String,
    pub name: String,
    pub program: String,
    pub args: Vec<String>,
    /// New on every registration, including an unchanged command using a different login.
    pub revision: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RegistrationInput {
    #[serde(default)]
    pub provider: Provider,
    pub id: String,
    pub name: String,
    pub program: String,
    pub args: Vec<String>,
}

fn checked(input: RegistrationInput) -> Result<Registration, String> {
    if input.id.is_empty()
        || input.id.len() > 48
        || !input
            .id
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
        || !input.id.as_bytes()[0].is_ascii_alphanumeric()
    {
        return Err(
            "Use an ID starting with a letter or digit, up to 48 lower-case letters, digits, hyphens or underscores."
                .into(),
        );
    }
    if input.name.trim().is_empty() || input.name.chars().count() > 120 || input.name.chars().any(char::is_control) {
        return Err("Give the agent a name of up to 120 characters, without control characters.".into());
    }
    if !Path::new(&input.program).is_absolute() || !Path::new(&input.program).is_file() {
        return Err("Choose the absolute path of an installed ACP executable.".into());
    }
    if input.args.len() > 32
        || input
            .args
            .iter()
            .any(|arg| arg.len() > 4096 || arg.chars().any(char::is_control))
    {
        return Err("Use at most 32 arguments of up to 4096 bytes, without control characters. Never put tokens or passwords in arguments.".into());
    }
    if matches!(
        input.provider,
        Provider::Antigravity | Provider::OpenCode | Provider::OpenCodeGo
    ) && input.args != ["acp"]
    {
        return Err(
            "This runtime template uses the acp command. Register other launch arguments as a separate custom agent."
                .into(),
        );
    }
    Ok(Registration {
        provider: input.provider,
        id: input.id,
        name: input.name.trim().to_owned(),
        program: input.program,
        args: input.args,
        revision: uuid::Uuid::new_v4().to_string(),
    })
}

#[tauri::command]
pub fn external_agents(app: AppHandle) -> Vec<Registration> {
    settings::current(&app).external_agents
}

/// The same lock guards registration changes and agent starts, so revocation cannot
/// finish between a launch's last check and process insertion.
pub(crate) static CHANGING: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

#[tauri::command]
pub async fn external_save_agent(app: AppHandle, registration: RegistrationInput) -> Result<Vec<Registration>, String> {
    let registration = checked(registration)?;
    let before = settings::current(&app).connection_revision;
    let (send, receive) = tokio::sync::oneshot::channel();
    let billing = match registration.provider {
        Provider::Antigravity => "Google personal OAuth is required; inherited Gemini API key variables are removed.",
        Provider::OpenCode => "OpenCode uses its own configured providers and credentials. Its model choices may include free models, Go and paid APIs.",
        Provider::OpenCodeGo => "Only an opencode-go primary model may receive a prompt. Connect Go under opencode-go in OpenCode itself; no key is copied by AgenticOS. Go Extra Usage and OpenCode auxiliary-model settings can incur additional charges. Coding tasks only.",
        Provider::Custom => "The program's own configuration decides subscription or API billing.",
    };
    app.dialog().message(format!(
        "Register {} ({})?\n\nProgram: {}\nArguments: {:?}\n\n{billing}\n\nThis program runs as your account without an OS sandbox. It owns its login, tools, model and charges. Read-only confinement is not guaranteed. Do not include credentials in arguments. Register it again after changing its account to clear saved sessions.",
        registration.name, registration.id, registration.program, registration.args,
    ))
        .title("Register an external ACP agent?").kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Register".into(), "Cancel".into()))
        .show(move |allowed| { let _ = send.send(allowed); });
    if !receive.await.unwrap_or(false) {
        return Err("Registration cancelled.".into());
    }
    let _changing = CHANGING.lock().await;
    if settings::current(&app).connection_revision != before {
        return Err("The connection changed. Register the agent again.".into());
    }
    crate::agent_session::close_external(&app, &registration.id).await;
    let (next, result) = settings::update(&app, |state| {
        if state.connection_revision != before {
            return Err("The connection changed. Register the agent again.");
        }
        if state.external_agents.len() >= 32 && !state.external_agents.iter().any(|agent| agent.id == registration.id) {
            return Err("Remove an external agent before registering another (limit 32).");
        }
        clear_history(state, &registration.id);
        state.external_agents.retain(|agent| agent.id != registration.id);
        state.external_agents.push(registration.clone());
        Ok(())
    })?;
    result?;
    Ok(next.external_agents)
}

fn clear_history(state: &mut settings::Settings, id: &str) {
    state.coding_sessions.retain(|item| !item.is_for_external(id));
    state.coding_consents.retain(|item| !item.is_for_external(id));
}

#[tauri::command]
pub async fn external_remove_agent(app: AppHandle, id: String) -> Result<Vec<Registration>, String> {
    let _changing = CHANGING.lock().await;
    crate::agent_session::close_external(&app, &id).await;
    let (next, ()) = settings::update(&app, |state| {
        state.external_agents.retain(|agent| agent.id != id);
        clear_history(state, &id);
    })?;
    Ok(next.external_agents)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn input() -> RegistrationInput {
        RegistrationInput {
            provider: Provider::Custom,
            id: "my-agent".into(),
            name: "My agent".into(),
            program: std::env::current_exe().unwrap().to_string_lossy().into_owned(),
            args: vec!["acp".into()],
        }
    }

    #[test]
    fn antigravity_registration_keeps_personal_login_separate_from_api_modes() {
        let registered = checked(RegistrationInput {
            provider: Provider::Antigravity,
            ..input()
        })
        .unwrap();
        assert_eq!(registered.provider, Provider::Antigravity);
        assert!(checked(RegistrationInput {
            provider: Provider::Antigravity,
            args: vec!["acp".into(), "--dangerously-skip-permissions".into()],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            provider: Provider::Antigravity,
            args: vec!["--api-key".into()],
            ..input()
        })
        .is_err());
    }

    #[test]
    fn opencode_templates_preserve_namespaces_and_refuse_launch_overrides() {
        for (provider, wire) in [(Provider::OpenCode, "opencode"), (Provider::OpenCodeGo, "opencode_go")] {
            let registered = checked(RegistrationInput { provider, ..input() }).unwrap();
            assert_eq!(registered.provider, provider);
            assert_eq!(serde_json::to_value(provider).unwrap(), wire);
            assert_eq!(
                serde_json::from_value::<Provider>(serde_json::json!(wire)).unwrap(),
                provider
            );
            assert!(checked(RegistrationInput {
                provider,
                args: vec!["acp".into(), "--model".into(), "other/model".into()],
                ..input()
            })
            .is_err());
        }
    }

    #[test]
    fn registrations_bound_commands_and_never_accept_remote_environment() {
        let one = checked(input()).unwrap();
        assert_ne!(one.revision, checked(input()).unwrap().revision);
        for id in ["", "-agent", "UPPER", "a b", "../agent"] {
            assert!(checked(RegistrationInput {
                id: id.into(),
                ..input()
            })
            .is_err());
        }
        assert!(checked(RegistrationInput {
            program: "agent".into(),
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            program: "/does-not-exist".into(),
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            args: vec!["x".into(); 33],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            args: vec!["a\nb".into()],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            name: "a\nb".into(),
            ..input()
        })
        .is_err());
        let mut wire = serde_json::json!({"id":"agent", "name":"Agent", "program":"/bin/agent", "args":[], "env":{"TOKEN":"hidden"}});
        assert!(serde_json::from_value::<RegistrationInput>(wire.clone()).is_err());
        wire.as_object_mut().unwrap().remove("env");
        assert!(serde_json::from_value::<RegistrationInput>(wire).is_ok());
    }
}
