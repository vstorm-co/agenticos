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
    Hermes,
    Antigravity,
    AntigravityApiKey,
    Cursor,
    CursorApiKey,
    Cline,
    ClineApiKey,
    MistralVibe,
    Grok,
    GrokApiKey,
    Kimi,
    QwenSubscription,
    Devin,
    Pi,
    PiInception,
    PiDeepseek,
    PiOpenrouter,
    Muse,
    MuseApiKey,
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
        Provider::Antigravity
            | Provider::AntigravityApiKey
            | Provider::Cursor
            | Provider::CursorApiKey
            | Provider::OpenCode
            | Provider::OpenCodeGo
            | Provider::Kimi
    ) && input.args != ["acp"]
    {
        return Err(
            "This runtime template uses the acp command. Register other launch arguments as a separate custom agent."
                .into(),
        );
    }
    if matches!(input.provider, Provider::Cline | Provider::ClineApiKey) && input.args != ["--acp"] {
        return Err(
            "The Cline template requires --acp without launch overrides. Register other commands as custom agents."
                .into(),
        );
    }
    if input.provider == Provider::Hermes && !input.args.is_empty() {
        return Err("Hermes requires its prepared Python executable without arguments; Desktop owns the foreground ACP adapter.".into());
    }
    if input.provider == Provider::MistralVibe && !input.args.is_empty() {
        return Err("Mistral Vibe requires the vibe-acp executable without arguments.".into());
    }
    if matches!(input.provider, Provider::Grok | Provider::GrokApiKey)
        && input.args != ["--no-auto-update", "agent", "stdio"]
    {
        return Err("Grok requires --no-auto-update agent stdio without extra launch flags.".into());
    }
    if input.provider == Provider::QwenSubscription && input.args != ["--acp", "--auth-type=qwen-subscription"] {
        return Err(
            "Qwen subscription requires --acp --auth-type=qwen-subscription without extra launch flags.".into(),
        );
    }
    if input.provider == Provider::Devin && input.args != ["--permission-mode", "normal", "acp"] {
        return Err("Devin requires --permission-mode normal acp without cloud or approval overrides.".into());
    }
    if matches!(
        input.provider,
        Provider::PiInception | Provider::PiDeepseek | Provider::PiOpenrouter
    ) && input.args
        != [
            "--mode",
            "rpc",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-mcp",
        ]
    {
        return Err("Pi vault-key templates require the isolated native launch without additional arguments.".into());
    }
    if input.provider == Provider::Pi && input.args != ["--mode", "rpc"] {
        return Err(
            "Pi requires --mode rpc without startup overrides. Choose its provider and model in Pi itself.".into(),
        );
    }
    if matches!(input.provider, Provider::Muse | Provider::MuseApiKey) && input.args != ["serve"] {
        return Err("Muse uses its pinned native SDK with muse serve. Startup overrides are not supported.".into());
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
        Provider::Muse => "Muse uses the pinned official SDK and your CLI configuration. Run muse and complete its login first. META_API_KEY and stored API keys take priority over a browser account; check the reported credential source. Login does not establish plan entitlement. Native tools and configured extensions retain local access. This is an owned foreground MSP host, not an attached daemon.",
        Provider::MuseApiKey => "Muse uses the required META_API_KEY inherited by Desktop. A missing key refuses launch without falling back to a browser login or stored key. The key stays local. This uses the pinned official SDK with an owned foreground muse serve host.",
        Provider::PiInception | Provider::PiDeepseek | Provider::PiOpenrouter => "This Pi API-key template receives only the selected vault key from a member independently allowed to view it. The key reaches this local program in memory and an isolated configuration, never in launch arguments or generated files. The registration must match the selected provider. Saved Pi login and discovered extensions are excluded. Pi 1.5.2 is required. API billing belongs to this key, with unpriced usage in AgenticOS. Native tools run with full local access.",
        Provider::Pi => "Pi uses its own saved configuration, extensions, login and API keys through native RPC. Run pi and choose its provider/model before registration. This runs the CLI with full local access; extensions and native tools retain that access. No platform tools or vault credentials are forwarded, and account/model catalogs do not prove subscription entitlement. Supported human extension dialogs appear in the live AgenticOS chat; secret input stays in Pi login. Charges are unpriced.",
        Provider::Devin => "Devin CLI uses its own account and advertised browser login. Complete devin auth login and check devin auth status first. Billing and enterprise CLI permission belong to your Devin account. This launches the local ACP agent, not --cloud or the Devin task API. Choose a model from its catalog; the selection applies only to this launch. CLI-owned tools and account data remain with Devin; AgenticOS forwards no platform tools.",
        Provider::QwenSubscription => "Qwen Code uses its own saved subscription login. Complete /auth in qwen first, choosing Qwen Account with Subscription. The child explicitly selects qwen-subscription and removes inherited OpenAI key, endpoint and model overrides. No authenticate operation or credential import is performed. Choose an advertised subscription model; it is passed only to this launch. Plan access and quotas require account verification.",
        Provider::Kimi => "Kimi uses its own configured login and providers. Complete kimi login first. AgenticOS checks login readiness without importing credentials. Custom models can use separately billed APIs; account login alone does not establish subscription billing. Choosing a model uses the source-checked Python host without changing saved defaults. Supported human questions appear in the live AgenticOS chat.",
        Provider::GrokApiKey => "Grok receives only the required XAI_API_KEY inherited by Desktop and an isolated scoped GROK_HOME. No saved login or provider configuration is copied. The CLI may save this key inside that private profile, whose auth.json is removed when the owned process exits while scoped sessions are retained. Missing keys refuse launch. API billing belongs to this key.",
        Provider::Grok => "Grok uses a cached CLI login. This child removes XAI_API_KEY and GROK_CODE_XAI_API_KEY and disables API-key authentication. The server refuses a runtime still advertising API-key auth. Finish grok login first. Grok account, gateway and plan settings determine billing; no API-key mode is supported by this template.",
        Provider::MistralVibe => "Vibe owns browser sign-in and API keys. Browser sign-in may provision or reuse an API key; it does not prove Le Chat subscription access. This child disables telemetry and enables Vibe's experimental model catalog. A selected model is set only in the child environment. Existing keyring, .env and project settings stay with Vibe. Usage is unpriced.",
        Provider::Cline => "Cline account login is required. Inherited API keys are removed and provider selection is fixed to Cline. Credit, model availability and any free offerings depend on your Cline account, not on an assumed subscription.",
        Provider::ClineApiKey => "Only the CLINE_API_KEY inherited by Desktop is used, with the provider fixed to Cline. A missing key refuses launch without using saved account credentials. No key is stored by AgenticOS. Cline account/credit terms determine charges.",
        Provider::CursorApiKey => "Cursor receives only the required CURSOR_API_KEY inherited by Desktop. Auth-token overrides are removed. Missing keys refuse launch; the saved browser login is not selected. API billing belongs to this key.",
        Provider::Cursor => "Cursor uses its own CLI account login; inherited API keys and auth-token overrides are removed. Account, model and on-demand settings determine charges. Sign in with agent login first. API-key registration is not supported by this template.",
        Provider::Antigravity => "Google personal OAuth is required; inherited Gemini API key variables are removed. Google's Additional Terms (section 6) restrict consumer sign-in through third-party tools, and Google may limit or suspend such accounts. You accepted this risk in the console; the Gemini API key template avoids it.",
        Provider::AntigravityApiKey => "A run uses the Gemini key its member chose from the AgenticOS vault, otherwise the GEMINI_API_KEY inherited by Desktop, with the gemini-api-key login. A missing key refuses launch without using the saved Google sign-in. Desktop stores no key. Gemini API pricing and terms determine charges, not a Google AI subscription.",
        Provider::OpenCode => "OpenCode uses its own configured providers and credentials. Its model choices may include free models, Go and paid APIs.",
        Provider::OpenCodeGo => "Only an opencode-go primary model may receive a prompt. Connect Go under opencode-go in OpenCode itself; no key is copied by AgenticOS. Go Extra Usage and OpenCode auxiliary-model settings can incur additional charges. Coding tasks only.",
        Provider::Hermes => "Select the Python executable in the documented Hermes environment, not the hermes command. Desktop starts a source-verified foreground ACP host, never the shared gateway. Each private conversation has a separate Hermes home; the native setup dialog identifies that home. Complete provider setup and Nous Portal login there. No existing home, memory, skills or token files are copied. Credentials, configured APIs, native tools and charges remain Hermes-owned. Changing the registration clears continuation and selects a fresh home. Usage is unpriced.",
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
    crate::agent_session::close_external(&app, &registration.id).await?;
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
    crate::agent_session::close_external(&app, &id).await?;
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
    fn muse_templates_require_owned_sdk_host_without_overrides() {
        for provider in [Provider::Muse, Provider::MuseApiKey] {
            assert!(checked(RegistrationInput {
                provider,
                args: vec!["serve".into()],
                ..input()
            })
            .is_ok());
            assert!(checked(RegistrationInput {
                provider,
                args: vec!["serve".into(), "--daemon".into()],
                ..input()
            })
            .is_err());
            assert!(checked(RegistrationInput { provider, ..input() }).is_err());
        }
    }

    #[test]
    fn pi_template_requires_native_rpc_without_launch_overrides() {
        assert!(checked(RegistrationInput {
            provider: Provider::Pi,
            args: vec!["--mode".into(), "rpc".into()],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::Pi,
            args: vec!["--mode".into(), "rpc".into(), "--continue".into()],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            provider: Provider::Pi,
            ..input()
        })
        .is_err());
    }

    #[test]
    fn devin_template_refuses_cloud_and_automatic_approval_modes() {
        assert!(checked(RegistrationInput {
            provider: Provider::Devin,
            args: vec!["--permission-mode".into(), "normal".into(), "acp".into()],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::Devin,
            args: vec!["--cloud".into(), "acp".into()],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            provider: Provider::Devin,
            args: vec!["--permission-mode".into(), "dangerous".into(), "acp".into()],
            ..input()
        })
        .is_err());
    }

    #[test]
    fn qwen_subscription_pins_auth_type_instead_of_inheriting_api_auth() {
        assert!(checked(RegistrationInput {
            provider: Provider::QwenSubscription,
            args: vec!["--acp".into(), "--auth-type=qwen-subscription".into()],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::QwenSubscription,
            args: vec!["--acp".into()],
            ..input()
        })
        .is_err());
        assert!(checked(RegistrationInput {
            provider: Provider::QwenSubscription,
            args: vec!["--acp".into(), "--auth-type=openai".into()],
            ..input()
        })
        .is_err());
    }

    #[test]
    fn kimi_template_refuses_config_and_auto_approval_overrides() {
        assert!(checked(RegistrationInput {
            provider: Provider::Kimi,
            args: vec!["acp".into()],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::Kimi,
            args: vec!["acp".into(), "--yolo".into()],
            ..input()
        })
        .is_err());
    }

    #[test]
    fn pi_key_templates_cannot_enable_discovered_extensions_or_override_the_launch() {
        let args: Vec<String> = [
            "--mode",
            "rpc",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-mcp",
        ]
        .into_iter()
        .map(str::to_owned)
        .collect();
        for provider in [Provider::PiInception, Provider::PiDeepseek, Provider::PiOpenrouter] {
            assert!(checked(RegistrationInput {
                provider,
                args: args.clone(),
                ..input()
            })
            .is_ok());
            assert!(checked(RegistrationInput {
                provider,
                args: vec!["--mode".into(), "rpc".into()],
                ..input()
            })
            .is_err());
        }
    }

    #[test]
    fn grok_template_requires_stdio_and_disabled_updates() {
        assert!(checked(RegistrationInput {
            provider: Provider::Grok,
            args: vec!["--no-auto-update".into(), "agent".into(), "stdio".into()],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::Grok,
            ..input()
        })
        .is_err());
    }

    #[test]
    fn vibe_template_uses_its_own_executable_without_startup_overrides() {
        assert!(checked(RegistrationInput {
            provider: Provider::MistralVibe,
            args: vec![],
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::MistralVibe,
            ..input()
        })
        .is_err());
    }

    #[test]
    fn cline_templates_require_foreground_acp_without_auto_approval_flags() {
        for provider in [Provider::Cline, Provider::ClineApiKey] {
            assert!(checked(RegistrationInput {
                provider,
                args: vec!["--acp".into()],
                ..input()
            })
            .is_ok());
            for args in [vec!["acp".into()], vec!["--acp".into(), "--yolo".into()]] {
                assert!(checked(RegistrationInput {
                    provider,
                    args,
                    ..input()
                })
                .is_err());
            }
        }
    }

    #[test]
    fn antigravity_key_registration_uses_the_same_fixed_launch() {
        assert!(checked(RegistrationInput {
            provider: Provider::AntigravityApiKey,
            ..input()
        })
        .is_ok());
        assert!(checked(RegistrationInput {
            provider: Provider::AntigravityApiKey,
            args: vec!["acp".into(), "--login".into()],
            ..input()
        })
        .is_err());
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
    fn runtime_templates_preserve_ids_and_refuse_launch_overrides() {
        for (provider, wire) in [
            (Provider::Cursor, "cursor"),
            (Provider::OpenCode, "opencode"),
            (Provider::OpenCodeGo, "opencode_go"),
        ] {
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
