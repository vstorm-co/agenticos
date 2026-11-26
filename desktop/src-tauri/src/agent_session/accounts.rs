//! Native-only Muse account operations; the remote task protocol exposes none.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tokio::io::AsyncWriteExt;

use super::{path_with, spawn_authenticated, Session};
use crate::external_agents::{Provider, Registration};

struct NativeFlow {
    id: String,
    cancel: Arc<AtomicBool>,
}

#[derive(Default)]
pub struct AccountFlows(StdMutex<Option<NativeFlow>>);

impl AccountFlows {
    pub(super) fn is_busy(&self) -> bool {
        self.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner()).is_some()
    }

    fn cancel(&self, request_id: &str) {
        let current = self.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if let Some(flow) = current.as_ref().filter(|flow| flow.id == request_id) {
            flow.cancel.store(true, Ordering::SeqCst);
        }
    }
}

struct FlowGuard<'a>(&'a AccountFlows);
impl Drop for FlowGuard<'_> {
    fn drop(&mut self) {
        *self.0 .0.lock().unwrap_or_else(|poisoned| poisoned.into_inner()) = None;
    }
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AccountAction {
    Status,
    SignIn,
    SignOut,
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub enum CredentialState {
    EnvKey,
    ApiKey,
    AccountLogin,
    LoggedOut,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AccountStatus {
    state: CredentialState,
    credential_required: bool,
}

fn status(value: Value) -> Result<AccountStatus, String> {
    serde_json::from_value(value).map_err(|_| "Muse returned an unsupported account state.".into())
}

async fn request(session: &Session, cursor: &mut u64, id: u32, method: &str, params: Value) -> Result<Value, String> {
    request_auth_status(session, cursor, id, method, params)
        .await?
        .ok_or_else(|| "The CLI requires sign-in.".into())
}

/// None is ACP's explicit authentication-required outcome, never a transport error.
async fn request_auth_status(
    session: &Session,
    cursor: &mut u64,
    id: u32,
    method: &str,
    params: Value,
) -> Result<Option<Value>, String> {
    let frame = serde_json::to_vec(&json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}))
        .map_err(|_| "Could not prepare the account operation.")?;
    let mut stdin = session.stdin.lock().await;
    stdin
        .write_all(&frame)
        .await
        .map_err(|_| "The CLI account connection closed.")?;
    stdin
        .write_all(b"\n")
        .await
        .map_err(|_| "The CLI account connection closed.")?;
    stdin.flush().await.map_err(|_| "The CLI account connection closed.")?;
    drop(stdin);
    tokio::time::timeout(
        Duration::from_secs(if method == "authenticate" { 600 } else { 30 }),
        async {
            loop {
                let changed = session.output.changed.notified();
                tokio::pin!(changed);
                changed.as_mut().enable();
                let (lines, next, exited, more) = {
                    let output = session
                        .output
                        .lines
                        .lock()
                        .unwrap_or_else(|poisoned| poisoned.into_inner());
                    let (lines, next) = output.since(*cursor)?;
                    (lines, next, output.exit.is_some(), next < output.end())
                };
                *cursor = next;
                for line in lines {
                    let frame: Value =
                        serde_json::from_str(&line).map_err(|_| "The CLI returned an invalid account response.")?;
                    if frame.get("id").and_then(Value::as_u64) != Some(u64::from(id)) {
                        continue;
                    }
                    if frame.get("error").is_some() {
                        if frame["error"]["code"].as_i64() == Some(-32000) {
                            return Ok(None);
                        }
                        return Err(
                            "The CLI refused the account operation. Check its version, login and environment key."
                                .into(),
                        );
                    }
                    return frame
                        .get("result")
                        .cloned()
                        .map(Some)
                        .ok_or_else(|| "The CLI returned no account result.".into());
                }
                if exited {
                    return Err("The CLI stopped before completing the account operation.".into());
                }
                if more {
                    continue;
                }
                changed.await;
            }
        },
    )
    .await
    .map_err(|_| "The CLI account operation timed out.")?
}

fn registration(app: &AppHandle, id: &str) -> Result<Registration, String> {
    crate::settings::current(app)
        .external_agents
        .into_iter()
        .find(|registration| {
            registration.id == id && matches!(registration.provider, Provider::Muse | Provider::MuseApiKey)
        })
        .ok_or_else(|| "Register Muse before managing its account.".into())
}

async fn confirm(app: &AppHandle, registration: &Registration, action: AccountAction) -> Result<(), String> {
    let action = match action {
        AccountAction::SignIn => "Sign in to Muse using its own device-code flow",
        AccountAction::SignOut => "Sign out of Muse and remove its stored account or API key",
        AccountAction::Status => return Ok(()),
    };
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!("{action}?\n\nProgram: {}\n\nAll Muse runtime tasks will stop and their saved continuations will be cleared because Muse accounts are shared by its local CLI. An inherited META_API_KEY remains active until removed from Desktop's environment. Account details and device codes stay on this computer.", registration.program))
        .title("Manage Muse account?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Continue".into(), "Cancel".into()))
        .show(move |allowed| { let _ = send.send(allowed); });
    if receive.await.unwrap_or(false) {
        Ok(())
    } else {
        Err("Account operation cancelled.".into())
    }
}

#[tauri::command]
pub fn external_cancel_muse_account(app: AppHandle, request_id: String) {
    let flows = app.state::<AccountFlows>();
    flows.cancel(&request_id);
}

#[tauri::command]
pub async fn external_muse_account(
    app: AppHandle,
    id: String,
    request_id: String,
    action: AccountAction,
) -> Result<AccountStatus, String> {
    uuid::Uuid::parse_str(&request_id).map_err(|_| "Start a new account operation.")?;
    let flows = app.state::<AccountFlows>();
    let cancel = Arc::new(AtomicBool::new(false));
    {
        let mut current = flows.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if current.is_some() {
            return Err("Finish the current account operation first.".into());
        }
        *current = Some(NativeFlow {
            id: request_id.clone(),
            cancel: Arc::clone(&cancel),
        });
    }
    let _flow = FlowGuard(&flows);
    let mut entry = registration(&app, &id)?;
    let connection = crate::settings::current(&app).connection_revision;
    if matches!(action, AccountAction::SignIn) && entry.provider == Provider::MuseApiKey {
        return Err(
            "This registration requires an environment API key. Use a Muse account registration for browser login."
                .into(),
        );
    }
    confirm(&app, &entry, action).await?;
    if cancel.load(Ordering::SeqCst) {
        return Err("Account operation cancelled.".into());
    }
    if !matches!(action, AccountAction::Status) {
        let _changing = crate::external_agents::CHANGING.lock().await;
        if crate::settings::current(&app).connection_revision != connection || registration(&app, &id)? != entry {
            return Err("The connection or registration changed. Start again.".into());
        }
        let muse_ids: Vec<String> = crate::settings::current(&app)
            .external_agents
            .into_iter()
            .filter(|item| matches!(item.provider, Provider::Muse | Provider::MuseApiKey))
            .map(|item| item.id)
            .collect();
        for muse_id in &muse_ids {
            super::close_external(&app, muse_id).await?;
        }
        let (updated, ()) = crate::settings::update(&app, |state| {
            state
                .coding_sessions
                .retain(|item| !muse_ids.iter().any(|id| item.is_for_external(id)));
            state
                .coding_consents
                .retain(|item| !muse_ids.iter().any(|id| item.is_for_external(id)));
            for item in &mut state.external_agents {
                if muse_ids.contains(&item.id) {
                    item.revision = uuid::Uuid::new_v4().to_string();
                }
            }
        })?;
        entry = updated
            .external_agents
            .into_iter()
            .find(|item| item.id == id)
            .ok_or("Muse registration changed.")?;
    }
    let runtime = crate::coding_runtime::prepare(&app).await?;
    if cancel.load(Ordering::SeqCst) {
        return Err("Account operation cancelled.".into());
    }
    let session = spawn_authenticated(
        &runtime.node,
        &[
            runtime.muse_adapter().to_string_lossy().into_owned(),
            entry.program.clone(),
            "--native-account-control".into(),
        ],
        &runtime.directory,
        path_with(&runtime.node),
        entry.provider,
    )
    .map_err(|_| "Could not start the managed Muse account connection.")?;
    if crate::settings::current(&app).connection_revision != connection
        || registration(&app, &id).as_ref() != Ok(&entry)
    {
        return Err("The connection or registration changed. Start again.".into());
    }
    let mut cursor = 0;
    request(&session, &mut cursor, 1, "initialize", json!({"protocolVersion":1})).await?;
    if !matches!(action, AccountAction::SignIn) {
        return status(
            request(
                &session,
                &mut cursor,
                2,
                if matches!(action, AccountAction::SignOut) {
                    "_auth/logout"
                } else {
                    "_auth/status"
                },
                json!({}),
            )
            .await?,
        );
    }
    let started = request(&session, &mut cursor, 2, "_auth/login_start", json!({})).await?;
    if cancel.load(Ordering::SeqCst)
        || crate::settings::current(&app).connection_revision != connection
        || registration(&app, &id).as_ref() != Ok(&entry)
    {
        let _ = request(&session, &mut cursor, 3, "_auth/login_cancel", json!({})).await;
        return Err("Account operation cancelled.".into());
    }

    let url = started
        .get("verificationUrl")
        .and_then(Value::as_str)
        .ok_or("Muse returned no sign-in address.")?;
    let code = started
        .get("userCode")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or("Muse returned no device code.")?;
    let parsed = tauri::Url::parse(url).map_err(|_| "Muse returned an invalid sign-in address.")?;
    if parsed.scheme() != "https" || !parsed.username().is_empty() || parsed.password().is_some() || url.len() > 2048 {
        return Err("Muse returned an invalid sign-in address.".into());
    }
    app.emit_to(
        crate::WINDOW,
        "external-account-progress",
        json!({"requestId":request_id,"verificationUrl":url,"userCode":code}),
    )
    .map_err(|_| "Could not display the Muse device code.")?;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(600);
    let mut sequence = 2;
    loop {
        if cancel.load(Ordering::SeqCst)
            || tokio::time::Instant::now() >= deadline
            || crate::settings::current(&app).connection_revision != connection
            || registration(&app, &id).as_ref() != Ok(&entry)
        {
            let _ = request(&session, &mut cursor, sequence + 1, "_auth/login_cancel", json!({})).await;
            return Err("Muse sign-in cancelled or expired. Start again when ready.".into());
        }
        sequence += 1;
        let current = status(request(&session, &mut cursor, sequence, "_auth/status", json!({})).await?)?;
        if current.state == CredentialState::AccountLogin {
            return Ok(current);
        }
        if current.state != CredentialState::LoggedOut {
            return Err("Another credential source became active. Check Muse's account before continuing.".into());
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_matching_native_flow_can_cancel_and_drop_releases_its_slot() {
        let cancelled = Arc::new(AtomicBool::new(false));
        let flows = AccountFlows(StdMutex::new(Some(NativeFlow {
            id: "ours".into(),
            cancel: Arc::clone(&cancelled),
        })));
        let guard = FlowGuard(&flows);
        flows.cancel("someone-else");
        assert!(!cancelled.load(Ordering::SeqCst));
        assert!(flows.is_busy());
        flows.cancel("ours");
        assert!(cancelled.load(Ordering::SeqCst));
        drop(guard);
        assert!(!flows.is_busy());
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn account_rpc_keeps_vendor_errors_out_of_the_ui() {
        let session = spawn_authenticated(
            std::path::Path::new("/bin/sh"),
            &["-c".into(), r#"read line; printf '%s\n' '{"jsonrpc":"2.0","id":1,"error":{"message":"SECRET-private-key"}}'; sleep 2"#.into()],
            std::path::Path::new("/tmp"), None, Provider::Custom,
        ).unwrap();
        let error = request(&session, &mut 0, 1, "initialize", json!({})).await.unwrap_err();
        assert!(!error.contains("SECRET"));
        assert!(error.contains("refused"));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn auth_required_is_a_signed_out_outcome_but_other_errors_still_fail() {
        let session = spawn_authenticated(
            std::path::Path::new("/bin/sh"),
            &["-c".into(), r#"read line; printf '%s\n' '{"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"SECRET"}}'; read line; printf '%s\n' '{"jsonrpc":"2.0","id":2,"error":{"code":-32603,"message":"SECRET"}}'"#.into()],
            std::path::Path::new("/tmp"), None, Provider::Custom,
        ).unwrap();
        let mut cursor = 0;
        assert!(request_auth_status(&session, &mut cursor, 1, "authenticate", json!({}))
            .await
            .unwrap()
            .is_none());
        let error = request_auth_status(&session, &mut cursor, 2, "authenticate", json!({}))
            .await
            .unwrap_err();
        assert!(error.contains("refused"));
        assert!(!error.contains("SECRET"));
    }

    #[test]
    fn account_status_never_returns_vendor_labels_or_keys() {
        let parsed = status(json!({"state":"accountLogin","credentialRequired":true,"apiKey":"private-key","label":"private@example.test"})).unwrap();
        assert_eq!(
            serde_json::to_value(parsed).unwrap(),
            json!({"state":"accountLogin","credentialRequired":true})
        );
        assert!(status(json!({"state":"unknown","credentialRequired":true})).is_err());
    }
}

#[derive(Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum CliAccountAction {
    Status,
    SignIn,
    Reconnect,
    SignOut,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CliAccountStatus {
    state: &'static str,
    sign_out_available: bool,
}

fn account_family(provider: Provider) -> Option<&'static str> {
    match provider {
        Provider::Cursor | Provider::CursorApiKey => Some("cursor"),
        Provider::Grok | Provider::GrokApiKey => Some("grok"),
        Provider::Kimi => Some("kimi"),
        Provider::Devin => Some("devin"),
        Provider::MistralVibe => Some("vibe"),
        _ => None,
    }
}

fn cli_arguments(provider: Provider, action: CliAccountAction) -> Result<Vec<&'static str>, String> {
    use CliAccountAction::*;
    let args: &[&str] = match (provider, action) {
        (Provider::Cursor, Status) => &["status"],
        (Provider::Cursor, SignIn | Reconnect) => &["login"],
        (Provider::Cursor, SignOut) => &["logout"],
        (Provider::Grok, SignIn | Reconnect) => &["--no-auto-update", "login"],
        (Provider::Grok, SignOut) => &["--no-auto-update", "logout"],
        (Provider::Kimi, SignIn | Reconnect) => &["login", "--json"],
        (Provider::Kimi, SignOut) => &["logout", "--json"],
        (Provider::Devin, Status) => &["auth", "status"],
        (Provider::Devin, SignIn | Reconnect) => &["auth", "login"],
        (Provider::Devin, SignOut) => &["auth", "logout"],
        _ => return Err("This registration does not support that CLI account operation.".into()),
    };
    Ok(args.to_vec())
}

fn cli_status(output: &str) -> CliAccountStatus {
    let lower = output.to_lowercase();
    let state = if lower.contains("not logged in")
        || lower.contains("not authenticated")
        || lower.contains("unauthenticated")
        || lower.contains("logged out")
    {
        "signed_out"
    } else if lower.contains("logged in") || lower.contains("authenticated") {
        "signed_in"
    } else {
        "unknown"
    };
    CliAccountStatus {
        state,
        sign_out_available: true,
    }
}

fn vibe_status(value: Value) -> Result<CliAccountStatus, String> {
    let authenticated = value
        .get("authenticated")
        .and_then(Value::as_bool)
        .ok_or("Vibe returned unsupported account status.")?;
    let removable = value
        .get("signOutAvailable")
        .and_then(Value::as_bool)
        .ok_or("Vibe returned unsupported sign-out status.")?;
    let source = value
        .get("authState")
        .and_then(Value::as_str)
        .ok_or("Vibe returned no credential source.")?;
    let state = match source {
        "process_env" if authenticated => "environment_key",
        "os_keyring" | "vibe_home_env_file" if authenticated => "signed_in",
        "signed_out" if !authenticated => "signed_out",
        _ => return Err("Vibe's configured provider has no supported account state.".into()),
    };
    Ok(CliAccountStatus {
        state,
        sign_out_available: removable,
    })
}

/// Device-only account control. The remote agent protocol cannot request these mutations.
#[tauri::command]
pub async fn external_cli_account(
    app: AppHandle,
    id: String,
    request_id: String,
    action: CliAccountAction,
) -> Result<CliAccountStatus, String> {
    uuid::Uuid::parse_str(&request_id).map_err(|_| "Start a new account operation.")?;
    let flows = app.state::<AccountFlows>();
    let cancel = Arc::new(AtomicBool::new(false));
    {
        let mut current = flows.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
        if current.is_some() {
            return Err("Finish the current account operation first.".into());
        }
        *current = Some(NativeFlow {
            id: request_id.clone(),
            cancel: Arc::clone(&cancel),
        });
    }
    let _flow = FlowGuard(&flows);
    let _changing = crate::external_agents::CHANGING.lock().await;
    let settings = crate::settings::current(&app);
    let entry = settings
        .external_agents
        .iter()
        .find(|entry| entry.id == id)
        .cloned()
        .ok_or("The registration was removed.")?;
    let family = account_family(entry.provider).ok_or("Use this CLI's own account setup.")?;
    if matches!(entry.provider, Provider::CursorApiKey | Provider::GrokApiKey) {
        return Err("This key template has no browser account. Use its account template to manage login.".into());
    }
    if action != CliAccountAction::Status {
        let (send, receive) = tokio::sync::oneshot::channel();
        app.dialog().message(format!("Change the {family} account using its own CLI?\n\nProgram: {}\n\nAll registrations of this CLI will stop and their continuations will be cleared before credentials change. Reconnect signs out first. Inherited environment keys cannot be removed here. Credentials and sign-in codes stay on this computer.", entry.program))
            .title("Manage CLI account?").kind(MessageDialogKind::Warning)
            .buttons(MessageDialogButtons::OkCancelCustom("Continue".into(), "Cancel".into()))
            .show(move |allowed| { let _ = send.send(allowed); });
        if !receive.await.unwrap_or(false) {
            return Err("Account operation cancelled.".into());
        }
        if cancel.load(Ordering::SeqCst)
            || crate::settings::current(&app).connection_revision != settings.connection_revision
        {
            return Err("Account operation cancelled or connection changed.".into());
        }
        let ids: Vec<String> = settings
            .external_agents
            .iter()
            .filter(|item| account_family(item.provider) == Some(family))
            .map(|item| item.id.clone())
            .collect();
        for id in &ids {
            super::close_external(&app, id).await?;
        }
        crate::settings::update(&app, |state| {
            state
                .coding_sessions
                .retain(|item| !ids.iter().any(|id| item.is_for_external(id)));
            state
                .coding_consents
                .retain(|item| !ids.iter().any(|id| item.is_for_external(id)));
            for item in &mut state.external_agents {
                if ids.contains(&item.id) {
                    item.revision = uuid::Uuid::new_v4().to_string();
                }
            }
        })?;
    }
    let mut native_process = None;
    let mut cli_process = None;
    let result = {
        let work = async {
            if entry.provider == Provider::MistralVibe
                || (action == CliAccountAction::Status && matches!(entry.provider, Provider::Grok | Provider::Kimi))
            {
                return acp_account(&app, &entry, action, &mut native_process).await;
            }
            if action == CliAccountAction::Reconnect {
                cli_account_process(&app, &entry, &request_id, CliAccountAction::SignOut, &mut cli_process).await?;
            }
            cli_account_process(&app, &entry, &request_id, action, &mut cli_process).await
        };
        tokio::pin!(work);
        tokio::select! {
            result = &mut work => result,
            _ = async { while !cancel.load(Ordering::SeqCst) && crate::settings::current(&app).connection_revision == settings.connection_revision { tokio::time::sleep(Duration::from_millis(100)).await; } } => Err("Account operation cancelled.".into()),
            _ = tokio::time::sleep(Duration::from_secs(600)) => Err("Account operation expired. Start again.".into()),
        }
    };
    // Keep the account/start lock until cancellation has stopped the actual
    // owner, not merely the future waiting for its browser response.
    if let Some(mut session) = native_process {
        if let Some(kill) = session.kill.take() {
            let _ = kill.send(());
        }
        super::await_stopped(&session.output).await?;
    }
    if let Some(mut child) = cli_process {
        let _ = child.0.start_kill();
        tokio::time::timeout(Duration::from_secs(15), child.0.wait())
            .await
            .map_err(|_| "The CLI account process has not stopped.")?
            .map_err(|_| "Could not confirm that the CLI account process stopped.")?;
    }
    result
}

async fn acp_account(
    app: &AppHandle,
    entry: &Registration,
    action: CliAccountAction,
    owned: &mut Option<Session>,
) -> Result<CliAccountStatus, String> {
    let directory = app
        .path()
        .app_data_dir()
        .map_err(|_| "Could not open the native settings directory.")?;
    *owned = Some(
        spawn_authenticated(
            std::path::Path::new(&entry.program),
            &entry.args,
            &directory,
            super::path_with(std::path::Path::new(&entry.program)),
            entry.provider,
        )
        .map_err(|_| "Could not start the account connection.")?,
    );
    let session = owned.as_ref().ok_or("The native account process is unavailable.")?;
    let mut cursor = 0;
    let initialized = request(
        session,
        &mut cursor,
        1,
        "initialize",
        json!({"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"agenticos-settings","version":"1"}}),
    )
    .await?;
    if initialized["protocolVersion"] != 1 {
        return Err("This CLI did not negotiate ACP version 1.".into());
    }
    if entry.provider != Provider::MistralVibe {
        let method = super::login_method(entry.provider).ok_or("No account login method.")?;
        let available = initialized["authMethods"]
            .as_array()
            .is_some_and(|methods| methods.iter().any(|entry| entry["id"] == method));
        if entry.provider == Provider::Kimi && available {
            let authenticated =
                request_auth_status(session, &mut cursor, 2, "authenticate", json!({"methodId":method})).await?;
            return Ok(CliAccountStatus {
                state: if authenticated.is_some() {
                    "signed_in"
                } else {
                    "signed_out"
                },
                sign_out_available: true,
            });
        }
        return Ok(CliAccountStatus {
            state: if available { "signed_in" } else { "signed_out" },
            sign_out_available: true,
        });
    }
    let before = vibe_status(request(session, &mut cursor, 2, "_auth/status", json!({})).await?)?;
    if matches!(action, CliAccountAction::SignOut | CliAccountAction::Reconnect) {
        if !before.sign_out_available {
            return Err(
                "Vibe cannot remove this credential source. Remove inherited keys in Desktop's environment.".into(),
            );
        }
        request(session, &mut cursor, 3, "_auth/signOut", json!({})).await?;
    }
    if matches!(action, CliAccountAction::SignIn | CliAccountAction::Reconnect) {
        let advertised = initialized["authMethods"]
            .as_array()
            .is_some_and(|methods| methods.iter().any(|entry| entry["id"] == "browser-auth"));
        if !advertised {
            return Err("This Vibe version does not advertise browser sign-in.".into());
        }
        request(
            session,
            &mut cursor,
            4,
            "authenticate",
            json!({"methodId":"browser-auth"}),
        )
        .await?;
    }
    vibe_status(request(session, &mut cursor, 5, "_auth/status", json!({})).await?)
}

async fn cli_account_process(
    app: &AppHandle,
    entry: &Registration,
    request_id: &str,
    action: CliAccountAction,
    owned: &mut Option<crate::local_work::CommandTree>,
) -> Result<CliAccountStatus, String> {
    use std::process::Stdio;
    use tokio::io::{AsyncBufReadExt, AsyncReadExt, BufReader};
    let mut command = tokio::process::Command::new(&entry.program);
    command
        .args(cli_arguments(entry.provider, action)?)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .kill_on_drop(true);
    // Login commands may open their own browser; ACP account environments prohibit that.
    if matches!(entry.provider, Provider::Cursor) {
        command.env_remove("CURSOR_API_KEY").env_remove("CURSOR_AUTH_TOKEN");
    }
    if entry.provider == Provider::Grok {
        command.env_remove("XAI_API_KEY").env_remove("GROK_CODE_XAI_API_KEY");
    }
    if let Some(path) = super::path_with(std::path::Path::new(&entry.program)) {
        command.env("PATH", path);
    }
    *owned = Some(crate::local_work::spawn_tree(command).map_err(|_| "Could not start the CLI account operation.")?);
    let child = owned.as_mut().ok_or("The CLI account process is unavailable.")?;
    let stdout = child.0.stdout().take().ok_or("CLI provided no account output.")?;
    let read = async {
        let mut reader = BufReader::new(stdout);
        let mut status_text = String::new();
        loop {
            let mut line = Vec::new();
            let count = (&mut reader)
                .take(16385)
                .read_until(b'\n', &mut line)
                .await
                .map_err(|_| "Could not read CLI account status.")?;
            if count == 0 {
                break;
            }
            if line.len() > 16384 {
                return Err("CLI account response exceeded its limit.");
            }
            let text = String::from_utf8_lossy(&line);
            if entry.provider == Provider::Kimi && action != CliAccountAction::SignOut {
                if let Ok(value) = serde_json::from_str::<Value>(&text) {
                    if value["type"] == "verification_url" {
                        let url = value["data"]["verification_url"]
                            .as_str()
                            .ok_or("Kimi returned no sign-in URL.")?;
                        let code = value["data"]["user_code"]
                            .as_str()
                            .ok_or("Kimi returned no sign-in code.")?;
                        let parsed = tauri::Url::parse(url).map_err(|_| "Kimi returned an invalid sign-in URL.")?;
                        if url.len() > 2048
                            || parsed.scheme() != "https"
                            || !parsed.username().is_empty()
                            || parsed.password().is_some()
                            || code.is_empty()
                            || code.len() > 128
                            || code.chars().any(char::is_control)
                        {
                            return Err("Kimi returned unsafe sign-in details.");
                        }
                        app.emit_to(
                            crate::WINDOW,
                            "external-account-progress",
                            json!({"requestId":request_id,"verificationUrl":url,"userCode":code}),
                        )
                        .map_err(|_| "Could not display Kimi sign-in.")?;
                    }
                }
            } else if status_text.len() + text.len() <= 16384 {
                status_text.push_str(&text);
            }
        }
        Ok::<_, &str>(status_text)
    };
    let (exit, output) = tokio::join!(child.0.wait(), read);
    let output = output?;
    if !exit
        .map_err(|_| "Could not await the CLI account operation.")?
        .success()
    {
        return Err("The CLI refused this account operation. Check its installation and browser login.".into());
    }
    Ok(if action == CliAccountAction::SignOut {
        CliAccountStatus {
            state: "signed_out",
            sign_out_available: true,
        }
    } else if action == CliAccountAction::Status {
        cli_status(&output)
    } else {
        CliAccountStatus {
            state: "signed_in",
            sign_out_available: true,
        }
    })
}

#[cfg(test)]
mod cli_tests {
    use super::*;

    #[test]
    fn account_commands_are_fixed_and_key_templates_cannot_mutate_browser_accounts() {
        for provider in [Provider::Cursor, Provider::Grok, Provider::Kimi, Provider::Devin] {
            for action in [
                CliAccountAction::SignIn,
                CliAccountAction::Reconnect,
                CliAccountAction::SignOut,
            ] {
                let args = cli_arguments(provider, action).unwrap();
                assert!(!args.is_empty());
                assert!(!args.contains(&"acp"));
            }
        }
        for provider in [
            Provider::CursorApiKey,
            Provider::GrokApiKey,
            Provider::Custom,
            Provider::Pi,
        ] {
            assert!(cli_arguments(provider, CliAccountAction::SignIn).is_err());
        }
        assert_eq!(account_family(Provider::Cursor), account_family(Provider::CursorApiKey));
        assert_eq!(account_family(Provider::Grok), account_family(Provider::GrokApiKey));
        assert_ne!(account_family(Provider::Grok), account_family(Provider::Cursor));
        assert_eq!(account_family(Provider::Custom), None);
    }

    #[test]
    fn vibe_reports_environment_keys_without_claiming_they_can_be_removed() {
        let status = vibe_status(json!({"authenticated":true,"authState":"process_env","signOutAvailable":false,"apiKey":"SECRET","user":"PRIVATE"})).unwrap();
        assert_eq!(status.state, "environment_key");
        assert!(!status.sign_out_available);
        let serialized = serde_json::to_string(&status).unwrap();
        assert!(!serialized.contains("SECRET") && !serialized.contains("PRIVATE"));
        assert_eq!(
            vibe_status(json!({"authenticated":false,"authState":"signed_out","signOutAvailable":false}))
                .unwrap()
                .state,
            "signed_out"
        );
        for source in ["os_keyring", "vibe_home_env_file"] {
            assert_eq!(
                vibe_status(json!({"authenticated":true,"authState":source,"signOutAvailable":true}))
                    .unwrap()
                    .state,
                "signed_in"
            );
        }
        for invalid in [
            json!({}),
            json!({"authenticated":true}),
            json!({"authenticated":true,"signOutAvailable":true}),
            json!({"authenticated":true,"signOutAvailable":true,"authState":"other"}),
        ] {
            assert!(vibe_status(invalid).is_err());
        }
    }

    #[test]
    fn cli_status_does_not_infer_authentication_from_a_successful_command_or_return_identity() {
        assert_eq!(cli_status("status command finished").state, "unknown");
        for text in ["Not authenticated", "Unauthenticated", "Not logged in", "Logged out"] {
            assert_eq!(cli_status(text).state, "signed_out");
        }
        let status = cli_status("Logged in: private@example.test SECRET-key");
        assert_eq!(status.state, "signed_in");
        assert!(!serde_json::to_string(&status).unwrap().contains("SECRET"));
    }
}
