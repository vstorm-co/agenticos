//! Read the installed harness's choices without starting a model turn.
use std::path::Path;
use std::process::Stdio;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager};
use tokio::io::{AsyncBufRead, AsyncBufReadExt, AsyncReadExt, AsyncWrite, AsyncWriteExt, BufReader};

use crate::local_agents::AgentId;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct Choice {
    pub value: String,
    pub name: String,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
pub struct Model {
    pub value: String,
    pub name: String,
    pub efforts: Vec<Choice>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Options {
    pub models: Vec<Model>,
    pub current_model: Option<String>,
    pub current_effort: Option<String>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum Entry {
    Choice(Choice),
    Group { options: Vec<Choice> },
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct ConfigOption {
    current_value: String,
    options: Vec<Entry>,
}

fn choices(value: &Value, category: &str) -> Result<(Option<String>, Vec<Choice>), String> {
    if category == "model" && value.get("models").is_some() {
        #[derive(Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct LegacyModel {
            model_id: String,
            name: String,
        }
        #[derive(Deserialize)]
        #[serde(rename_all = "camelCase")]
        struct LegacyModels {
            current_model_id: String,
            available_models: Vec<LegacyModel>,
        }
        let models: LegacyModels = serde_json::from_value(value["models"].clone())
            .map_err(|_| "The agent returned malformed legacy models.")?;
        return Ok((
            Some(models.current_model_id),
            models
                .available_models
                .into_iter()
                .map(|model| Choice {
                    value: model.model_id,
                    name: model.name,
                })
                .collect(),
        ));
    }
    let selected = value["configOptions"].as_array().and_then(|options| {
        options
            .iter()
            .find(|option| option["category"].as_str() == Some(category))
    });
    let Some(selected) = selected else {
        return Ok((None, Vec::new()));
    };
    let option: ConfigOption =
        serde_json::from_value(selected.clone()).map_err(|_| "The coding agent returned invalid model settings.")?;
    let choices = option
        .options
        .into_iter()
        .flat_map(|entry| match entry {
            Entry::Choice(choice) => vec![choice],
            Entry::Group { options } => options,
        })
        .collect();
    Ok((Some(option.current_value), choices))
}

fn claude_options(value: &Value) -> Result<Options, String> {
    let (current_model, models) = choices(value, "model")?;
    let (current_effort, efforts) = choices(value, "thought_level")?;
    validate(Options {
        models: models
            .into_iter()
            .map(|choice| Model {
                value: choice.value,
                name: choice.name,
                efforts: efforts.clone(),
            })
            .collect(),
        current_model,
        current_effort,
    })
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CodexModel {
    model: String,
    display_name: String,
    default_reasoning_effort: String,
    is_default: bool,
    supported_reasoning_efforts: Vec<CodexEffort>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct CodexEffort {
    reasoning_effort: String,
}

#[derive(Deserialize)]
struct CodexModels {
    data: Vec<CodexModel>,
}

fn codex_options(models: Value, config: Value) -> Result<Options, String> {
    let models: CodexModels = serde_json::from_value(models).map_err(|_| "Codex returned invalid model settings.")?;
    let current_model = config["config"]["model"].as_str().map(str::to_owned).or_else(|| {
        models
            .data
            .iter()
            .find(|model| model.is_default)
            .map(|model| model.model.clone())
    });
    let current_effort = config["config"]["model_reasoning_effort"]
        .as_str()
        .map(str::to_owned)
        .or_else(|| {
            models
                .data
                .iter()
                .find(|model| Some(&model.model) == current_model.as_ref())
                .map(|model| model.default_reasoning_effort.clone())
        });
    validate(Options {
        models: models
            .data
            .into_iter()
            .map(|model| Model {
                value: model.model,
                name: model.display_name,
                efforts: model
                    .supported_reasoning_efforts
                    .into_iter()
                    .map(|effort| Choice {
                        name: effort.reasoning_effort.clone(),
                        value: effort.reasoning_effort,
                    })
                    .collect(),
            })
            .collect(),
        current_model,
        current_effort,
    })
}

fn validate(options: Options) -> Result<Options, String> {
    let identifier = |value: &str| {
        !value.is_empty() && value.len() <= 256 && !value.chars().any(|c| c.is_control() || c.is_whitespace())
    };
    let label = |value: &str| !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control);
    if options.models.is_empty()
        || options.models.len() > 128
        || options.models.iter().any(|model| {
            !identifier(&model.value)
                || !label(&model.name)
                || model.efforts.len() > 16
                || model
                    .efforts
                    .iter()
                    .any(|choice| !identifier(&choice.value) || !label(&choice.name))
        })
        || options.current_model.as_deref().is_some_and(|value| !identifier(value))
        || options
            .current_effort
            .as_deref()
            .is_some_and(|value| !identifier(value))
    {
        return Err(
            "The coding agent did not provide usable model choices. Check its sign-in in Settings and refresh.".into(),
        );
    }
    Ok(options)
}

async fn request(
    input: &mut (impl AsyncWrite + Unpin),
    output: &mut (impl AsyncBufRead + Unpin),
    id: u64,
    method: &str,
    params: Value,
) -> Result<Value, String> {
    let mut message = serde_json::to_vec(&json!({"jsonrpc":"2.0", "id":id, "method":method, "params":params}))
        .map_err(|e| e.to_string())?;
    message.push(b'\n');
    input
        .write_all(&message)
        .await
        .map_err(|_| "The coding agent stopped before returning its settings.")?;
    input
        .flush()
        .await
        .map_err(|_| "The coding agent could not read the settings request.")?;
    for _ in 0..256 {
        let mut line = Vec::new();
        let count = (&mut *output)
            .take(1024 * 1024 + 1)
            .read_until(b'\n', &mut line)
            .await
            .map_err(|_| "Could not read the coding agent's settings.")?;
        if count == 0 || count > 1024 * 1024 {
            return Err("The coding agent did not return bounded settings.".into());
        }
        let message: Value =
            serde_json::from_slice(&line).map_err(|_| "The coding agent returned unreadable settings.")?;
        if message["method"] == "session/request_permission" {
            return Err("The settings check unexpectedly requested tool access and was stopped.".into());
        }
        if message["id"] == id {
            if message.get("error").is_some() {
                return Err(
                    "The coding agent could not provide settings. Check its sign-in in Settings and refresh.".into(),
                );
            }
            return message
                .get("result")
                .cloned()
                .ok_or("The coding agent returned no settings.".into());
        }
    }
    Err("The coding agent sent too many messages while checking its settings.".into())
}

/// Whose choices are read: a managed builtin harness, or a registered ACP CLI.
#[derive(Clone, Copy)]
enum Target<'a> {
    Builtin(&'a crate::coding_runtime::Runtime, AgentId),
    External(&'a crate::external_agents::Registration),
}

/// Registrations whose catalog this probe can read like a session would.
///
/// Pi and Muse speak their own protocols, Hermes keeps a home per private
/// conversation, and some CLIs choose their model themselves.
fn readable_catalog(provider: crate::external_agents::Provider) -> bool {
    use crate::external_agents::Provider;
    !matches!(
        provider,
        Provider::Hermes
            | Provider::Pi
            | Provider::PiInception
            | Provider::PiDeepseek
            | Provider::PiOpenrouter
            | Provider::Muse
            | Provider::MuseApiKey
    )
}

async fn probe(target: Target<'_>, directory: &Path) -> Result<Options, String> {
    let working_directory = directory
        .to_str()
        .ok_or("The settings directory is not a valid text path.")?;
    let mut command = match target {
        Target::Builtin(runtime, id @ AgentId::ClaudeCode) => {
            let mut command = runtime.command()?;
            command.arg(runtime.adapter(id));
            command
        }
        Target::Builtin(runtime, id @ AgentId::Codex) => {
            let (program, prefix) = runtime.cli(id)?;
            let mut command = tokio::process::Command::new(program);
            command.args(prefix).arg("app-server");
            command
        }
        Target::External(registration) => {
            let program = Path::new(&registration.program);
            let mut command = tokio::process::Command::new(program);
            command.args(&registration.args);
            // The catalog must describe the same credential a session of this registration uses.
            crate::agent_session::provider_environment(&mut command, registration.provider, None)
                .map_err(|refusal| refusal.message)?;
            if let Some(path) = crate::agent_session::path_with(program) {
                command.env("PATH", path);
            }
            command
        }
    };
    let _key_profile = if let Target::External(registration) = target {
        crate::agent_session::key_profile(&mut command, registration.provider).map_err(|refusal| refusal.message)?
    } else {
        None
    };
    command
        .current_dir(directory)
        .env_remove("CLAUDE_CODE_EXECUTABLE")
        .env_remove("CODEX_PATH")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = crate::local_work::spawn_tree(command).map_err(|e| e.message)?;
    let mut input = child
        .0
        .stdin()
        .take()
        .ok_or("The coding agent provided no input pipe.")?;
    let mut output = BufReader::new(
        child
            .0
            .stdout()
            .take()
            .ok_or("The coding agent provided no output pipe.")?,
    );
    let result = tokio::time::timeout(Duration::from_secs(45), async {
        match target {
            Target::External(registration) => {
                let initialized = request(&mut input, &mut output, 1, "initialize", json!({"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"agenticos-settings","version":"1"}})).await?;
                if let Some(method) = crate::agent_session::login_method(registration.provider) {
                    advertised_login(&initialized, method)?;
                    let mut parameters = json!({"methodId":method});
                    if matches!(method, "cached_token" | "xai.api_key") {
                        parameters["_meta"] = json!({"headless": true});
                    }
                    request(&mut input, &mut output, 2, "authenticate", parameters).await?;
                } else if initialized["protocolVersion"] != 1 {
                    return Err("This agent did not negotiate ACP protocol version 1.".into());
                }
                let session = request(&mut input, &mut output, 3, "session/new", json!({"cwd":working_directory,"mcpServers":[]})).await?;
                if choices(&session, "model")?.0.is_some() {
                    claude_options(&session)
                } else {
                    // Some CLIs announce their catalog in an update right after the session opens.
                    claude_options(&config_update(&mut output).await?)
                }
            }
            Target::Builtin(_, AgentId::ClaudeCode) => {
                request(&mut input, &mut output, 1, "initialize", json!({"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"agenticos-settings","version":"1"}})).await?;
                let session = request(&mut input, &mut output, 2, "session/new", json!({"cwd":working_directory,"mcpServers":[],"_meta":{"claudeCode":{"options":{"persistSession":false,"tools":[],"mcpServers":{},"settingSources":[],"plugins":[]}}}})).await?;
                claude_options(&session)
            }
            Target::Builtin(_, AgentId::Codex) => {
                request(&mut input, &mut output, 1, "initialize", json!({"clientInfo":{"name":"agenticos-settings","version":"1"},"capabilities":{"experimentalApi":true}})).await?;
                let models = request(&mut input, &mut output, 2, "model/list", json!({"limit":100,"includeHidden":false})).await?;
                let config = request(&mut input, &mut output, 3, "config/read", json!({"includeLayers":false})).await?;
                codex_options(models, config)
            }
        }
    }).await.map_err(|_| "The coding agent took too long to return its settings.".to_owned()).and_then(|value| value);
    let _ = child.0.start_kill();
    let closed = tokio::time::timeout(Duration::from_secs(5), child.0.wait()).await;
    drop(child);
    match (result, closed) {
        (Err(error), _) => Err(error),
        (Ok(options), Ok(Ok(_))) => Ok(options),
        _ => Err("The coding settings process could not be closed.".into()),
    }
}

/// Refuse a CLI that does not advertise the login this registration's sessions enforce.
fn advertised_login(initialized: &Value, method: &str) -> Result<(), String> {
    if initialized["protocolVersion"] != 1 {
        return Err("This agent did not negotiate ACP protocol version 1.".into());
    }
    let advertised = initialized["authMethods"]
        .as_array()
        .is_some_and(|methods| methods.iter().any(|advertised| advertised["id"] == method));
    if !advertised {
        return Err(format!(
            "This agent does not offer the {method} login. Check its version and sign-in; no other account or billing mode was selected."
        ));
    }
    if method == "cached_token"
        && initialized["authMethods"]
            .as_array()
            .is_some_and(|methods| methods.iter().any(|advertised| advertised["id"] == "xai.api_key"))
    {
        return Err("Grok account mode requires API-key authentication to be disabled; no models were read.".into());
    }
    Ok(())
}

/// The first catalog update after a session opens, bounded in time and size.
async fn config_update(output: &mut (impl AsyncBufRead + Unpin)) -> Result<Value, String> {
    let unavailable = || "This agent did not announce model choices. Check its sign-in and refresh.".to_owned();
    tokio::time::timeout(Duration::from_secs(5), async {
        for _ in 0..256 {
            let mut line = Vec::new();
            let count = (&mut *output)
                .take(1024 * 1024 + 1)
                .read_until(b'\n', &mut line)
                .await
                .map_err(|_| unavailable())?;
            if count == 0 || count > 1024 * 1024 {
                return Err(unavailable());
            }
            let Ok(message) = serde_json::from_slice::<Value>(&line) else {
                continue;
            };
            let update = &message["params"]["update"];
            if message["method"] == "session/update" && update["sessionUpdate"] == "config_option_update" {
                return Ok(json!({"configOptions": update["configOptions"].clone()}));
            }
        }
        Err(unavailable())
    })
    .await
    .map_err(|_| unavailable())?
}

#[tauri::command]
pub async fn local_agent_options(app: AppHandle, id: AgentId) -> Result<Options, String> {
    let runtime = crate::coding_runtime::prepare(&app).await?;
    in_scratch(&app, Target::Builtin(&runtime, id)).await
}

/// A registered ACP CLI's models under its own login, without a model turn.
#[tauri::command]
pub async fn external_agent_options(app: AppHandle, id: String) -> Result<Options, String> {
    let registration = crate::settings::current(&app)
        .external_agents
        .into_iter()
        .find(|item| item.id == id)
        .ok_or("That ACP registration no longer exists.")?;
    if !readable_catalog(registration.provider) {
        return Err("This agent chooses its model itself; select it in the agent's own settings.".into());
    }
    in_scratch(&app, Target::External(&registration)).await
}

async fn in_scratch(app: &AppHandle, target: Target<'_>) -> Result<Options, String> {
    let directory = app
        .path()
        .app_cache_dir()
        .map_err(|e| e.to_string())?
        .join(format!("coding-options-{}", uuid::Uuid::new_v4()));
    tokio::fs::create_dir_all(&directory).await.map_err(|e| e.to_string())?;
    let result = async {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            tokio::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
                .await
                .map_err(|e| e.to_string())?;
        }
        probe(target, &directory).await
    }
    .await;
    let removed = tokio::fs::remove_dir_all(directory).await;
    match (result, removed) {
        (Ok(options), Ok(())) => Ok(options),
        (Err(error), _) => Err(error),
        (_, Err(_)) => Err("Could not remove the temporary coding settings directory.".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn external_options_require_the_registrations_login_and_protocol_one() {
        let both = json!({"protocolVersion":1,"authMethods":[{"id":"gemini-api-key"},{"id":"oauth-personal"}]});
        assert!(advertised_login(&both, "oauth-personal").is_ok());
        assert!(advertised_login(&both, "gemini-api-key").is_ok());
        let key_only = json!({"protocolVersion":1,"authMethods":[{"id":"gemini-api-key"}]});
        assert!(advertised_login(&key_only, "oauth-personal")
            .unwrap_err()
            .contains("no other account"));
        assert!(advertised_login(
            &json!({"protocolVersion":2,"authMethods":[{"id":"oauth-personal"}]}),
            "oauth-personal"
        )
        .is_err());
        assert!(advertised_login(&json!({"protocolVersion":1}), "login").is_err());
        let grok = json!({"protocolVersion":1,"authMethods":[{"id":"cached_token"},{"id":"xai.api_key"}]});
        assert!(advertised_login(&grok, "cached_token").unwrap_err().contains("API-key"));
    }

    #[test]
    fn only_acp_registrations_with_session_models_are_probed() {
        use crate::external_agents::Provider;
        for provider in [
            Provider::Custom,
            Provider::Antigravity,
            Provider::Cursor,
            Provider::Cline,
            Provider::Grok,
            Provider::OpenCode,
            Provider::Kimi,
            Provider::Devin,
            Provider::QwenSubscription,
            Provider::MistralVibe,
        ] {
            assert!(readable_catalog(provider), "{provider:?}");
        }
        for provider in [Provider::Hermes, Provider::Pi, Provider::PiDeepseek, Provider::Muse] {
            assert!(!readable_catalog(provider), "{provider:?}");
        }
    }

    #[tokio::test]
    async fn a_catalog_update_after_the_session_opens_is_read() {
        let stream = concat!(
            "not json\n",
            r#"{"jsonrpc":"2.0","method":"session/update","params":{"update":{"sessionUpdate":"agent_message_chunk"}}}"#,
            "\n",
            r#"{"jsonrpc":"2.0","method":"session/update","params":{"update":{"sessionUpdate":"config_option_update","configOptions":[{"category":"model","currentValue":"a","options":[{"value":"a","name":"A"}]}]}}}"#,
            "\n",
        );
        let mut reader = BufReader::new(stream.as_bytes());
        let options = claude_options(&config_update(&mut reader).await.unwrap()).unwrap();
        assert_eq!(options.models[0].value, "a");
        let mut empty = BufReader::new(&b""[..]);
        assert!(config_update(&mut empty)
            .await
            .unwrap_err()
            .contains("did not announce"));
    }

    #[test]
    fn claude_exposes_grouped_models_and_the_actual_reasoning_choices() {
        let options = claude_options(&json!({"configOptions":[
            {"category":"mode","currentValue":false},
            {"category":"model","currentValue":"haiku","options":[{"value":"haiku","name":"Haiku"},{"options":[{"value":"sonnet[1m]","name":"Sonnet (long context)"}]}]},
            {"category":"thought_level","currentValue":"low","options":[{"value":"low","name":"Low"},{"value":"high","name":"High"}]}
        ]})).unwrap();
        assert_eq!(options.models.len(), 2);
        assert_eq!(options.models[1].value, "sonnet[1m]");
        assert_eq!(options.models[0].efforts[0].value, "low");
        assert_eq!(options.current_effort.as_deref(), Some("low"));
        assert!(claude_options(&json!({"configOptions":[{"category":"model","options":false}]})).is_err());
        assert!(claude_options(&json!({})).is_err());
    }

    #[test]
    fn codex_choices_retain_each_models_own_levels_and_the_persons_config() {
        let models = json!({"data":[
            {"model":"fast","displayName":"Fast","isDefault":true,"defaultReasoningEffort":"low","supportedReasoningEfforts":[{"reasoningEffort":"low"}]},
            {"model":"deep","displayName":"Deep","isDefault":false,"defaultReasoningEffort":"high","supportedReasoningEfforts":[{"reasoningEffort":"high"},{"reasoningEffort":"max"}]}
        ]});
        let options = codex_options(
            models.clone(),
            json!({"config":{"model":"deep","model_reasoning_effort":"max"}}),
        )
        .unwrap();
        assert_eq!(options.current_model.as_deref(), Some("deep"));
        assert_eq!(options.current_effort.as_deref(), Some("max"));
        assert_eq!(options.models[0].efforts.len(), 1);
        assert_eq!(options.models[1].efforts.len(), 2);
        let defaults = codex_options(models, json!({"config":{}})).unwrap();
        assert_eq!(defaults.current_model.as_deref(), Some("fast"));
        assert_eq!(defaults.current_effort.as_deref(), Some("low"));
        assert!(codex_options(json!({"data":false}), json!({})).is_err());
    }

    #[test]
    fn invalid_or_unbounded_choices_are_not_presented_as_usable() {
        for value in ["", "a\nb", "a b", &"a".repeat(257)] {
            assert!(validate(Options {
                models: vec![Model {
                    value: value.into(),
                    name: "Model".into(),
                    efforts: vec![]
                }],
                current_model: None,
                current_effort: None
            })
            .is_err());
        }
    }

    #[tokio::test]
    async fn settings_requests_ignore_notifications_and_send_only_the_named_rpc() {
        let (mut input, mut sent) = tokio::io::duplex(4096);
        let bytes = b"{\"method\":\"initialized\"}\n{\"id\":7,\"result\":{\"data\":[]}}\n";
        let mut output = BufReader::new(&bytes[..]);
        assert_eq!(
            request(&mut input, &mut output, 7, "model/list", json!({"limit":100}))
                .await
                .unwrap(),
            json!({"data":[]})
        );
        drop(input);
        let mut bytes = Vec::new();
        sent.read_to_end(&mut bytes).await.unwrap();
        let message: Value = serde_json::from_slice(&bytes).unwrap();
        assert_eq!(message["method"], "model/list");
        assert_eq!(message["params"]["limit"], 100);
    }

    #[tokio::test]
    async fn settings_never_answer_tool_permissions_or_accept_a_vendor_error() {
        for response in [
            "",
            "not json\n",
            "{\"id\":7,\"error\":{\"message\":\"private detail\"}}\n",
            "{\"method\":\"session/request_permission\"}\n",
            "{\"id\":7}\n",
        ] {
            let mut input = tokio::io::sink();
            let mut output = BufReader::new(response.as_bytes());
            let error = request(&mut input, &mut output, 7, "model/list", json!({}))
                .await
                .unwrap_err();
            assert!(!error.contains("private detail"));
        }
    }

    #[tokio::test]
    #[ignore = "Requires the prepared desktop/runtime developer tooling and a signed-in account; never sends a model prompt"]
    async fn installed_harnesses_return_choices_and_are_closed_after_the_probe() {
        let runtime = crate::coding_runtime::Runtime {
            node: crate::local_agents::locate("node").expect("Node installed for this opt-in developer test"),
            directory: std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../runtime"),
        };
        let directory = std::env::temp_dir().join(format!("agenticos-options-smoke-{}", uuid::Uuid::new_v4()));
        tokio::fs::create_dir_all(&directory).await.unwrap();
        for agent in [AgentId::ClaudeCode, AgentId::Codex] {
            let options = probe(Target::Builtin(&runtime, agent), &directory).await.unwrap();
            assert!(!options.models.is_empty());
        }
        tokio::fs::remove_dir_all(directory).await.unwrap();
    }
}
