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
    let frame = serde_json::to_vec(&json!({"jsonrpc":"2.0","id":id,"method":method,"params":params}))
        .map_err(|_| "Could not prepare the account operation.")?;
    let mut stdin = session.stdin.lock().await;
    stdin
        .write_all(&frame)
        .await
        .map_err(|_| "Muse account connection closed.")?;
    stdin
        .write_all(b"\n")
        .await
        .map_err(|_| "Muse account connection closed.")?;
    stdin.flush().await.map_err(|_| "Muse account connection closed.")?;
    drop(stdin);
    tokio::time::timeout(Duration::from_secs(30), async {
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
                    serde_json::from_str(&line).map_err(|_| "Muse returned an invalid account response.")?;
                if frame.get("id").and_then(Value::as_u64) != Some(u64::from(id)) {
                    continue;
                }
                if frame.get("error").is_some() {
                    return Err(
                        "Muse refused the account operation. Check its version, login and environment key.".into(),
                    );
                }
                return frame
                    .get("result")
                    .cloned()
                    .ok_or_else(|| "Muse returned no account result.".into());
            }
            if exited {
                return Err("Muse stopped before completing the account operation.".into());
            }
            if more {
                continue;
            }
            changed.await;
        }
    })
    .await
    .map_err(|_| "Muse account operation timed out.")?
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
            super::close_external(&app, muse_id).await;
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
