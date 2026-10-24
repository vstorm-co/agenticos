//! Explicitly approved loopback services. The server names a grant, never a URL.

use crate::settings;
use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::AppHandle;
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

const LIMIT: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Kind {
    Model,
    Mcp,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Service {
    pub id: String,
    pub name: String,
    pub kind: Kind,
    pub endpoint: String,
    /// The installed model's exact identifier; never chosen by the server.
    pub model: Option<String>,
}

fn checked(mut service: Service) -> Result<Service, String> {
    if service.id.is_empty()
        || service.id.len() > 48
        || !service.id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        return Err("Use up to 48 letters, digits or underscores for the service ID.".into());
    }
    if service.name.trim().is_empty() || service.name.chars().count() > 120 {
        return Err("Give this service a name (up to 120 characters).".into());
    }
    let mut url = tauri::Url::parse(&service.endpoint).map_err(|_| "Enter a loopback HTTP address.")?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err("Use an HTTP address without credentials, query or fragment.".into());
    }
    match url.host_str() {
        Some("localhost") => {
            url.set_host(Some("127.0.0.1")).map_err(|e| e.to_string())?;
        }
        Some("127.0.0.1" | "[::1]") => {}
        _ => return Err("Local services must listen on 127.0.0.1, localhost or [::1].".into()),
    }
    match service.kind {
        Kind::Model
            if service
                .model
                .as_ref()
                .is_none_or(|m| m.trim().is_empty() || m.chars().count() > 200) =>
        {
            return Err("Name the model installed in this service.".into())
        }
        Kind::Mcp if service.model.is_some() => return Err("An MCP service has no model name.".into()),
        _ => {}
    }
    service.endpoint = url.to_string().trim_end_matches('/').to_owned();
    Ok(service)
}

#[tauri::command]
pub fn local_services(app: AppHandle) -> Vec<Service> {
    settings::current(&app).local_services
}

#[tauri::command]
pub async fn local_save_service(app: AppHandle, service: Service) -> Result<Vec<Service>, String> {
    let service = checked(service)?;
    let (send, receive) = tokio::sync::oneshot::channel();
    app.dialog().message(format!("Allow your agents to use {} at {} on this computer?\n\nRequests can send conversation content to this service. An MCP server can act with your local account's permissions.", service.name, service.endpoint))
        .title("Connect a local service?").kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Connect".into(), "Cancel".into()))
        .show(move |allowed| { let _ = send.send(allowed); });
    if !receive.await.unwrap_or(false) {
        return Err("Connection cancelled.".into());
    }
    let (next, ()) = settings::update(&app, |state| {
        state.local_services.retain(|s| s.id != service.id);
        state.local_services.push(service);
    })?;
    Ok(next.local_services)
}

#[tauri::command]
pub fn local_remove_service(app: AppHandle, id: String) -> Result<Vec<Service>, String> {
    let (next, ()) = settings::update(&app, |state| state.local_services.retain(|s| s.id != id))?;
    Ok(next.local_services)
}

pub async fn run(app: &AppHandle, op: &str, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    let id = args
        .get("service")
        .and_then(Value::as_str)
        .ok_or("Name an approved local service.")?;
    let service = settings::current(app)
        .local_services
        .into_iter()
        .find(|s| s.id == id)
        .ok_or("This local service has not been approved, or was removed.")?;
    let service = checked(service)?;
    if op == "service.describe" {
        return Ok(
            serde_json::from_value(serde_json::to_value(service).map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?,
        );
    }
    if op != "service.request" {
        return Err("Unknown local service operation.".into());
    }
    request(&service, args).await
}

async fn request(service: &Service, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    let method = args
        .get("method")
        .and_then(Value::as_str)
        .ok_or("No method was supplied.")?;
    let suffix = args.get("path").and_then(Value::as_str).unwrap_or("");
    // Neither a model nor a server can turn this grant into a general loopback proxy.
    let allowed = match service.kind {
        Kind::Model => method == "POST" && suffix == "/chat/completions",
        Kind::Mcp => suffix.is_empty() && matches!(method, "POST" | "GET" | "DELETE"),
    };
    if !allowed {
        return Err("That request is outside this service's grant.".into());
    }
    // Streamable HTTP's optional server event stream is not used by this relay.
    if method == "GET" {
        return Ok(
            serde_json::from_value(serde_json::json!({"status":405,"headers":{},"body":""}))
                .map_err(|e| e.to_string())?,
        );
    }
    let raw = args.get("body").and_then(Value::as_str).unwrap_or("");
    if raw.len() > LIMIT * 2 {
        return Err("The local request is too large.".into());
    }
    let body = base64::engine::general_purpose::STANDARD
        .decode(raw)
        .map_err(|_| "Invalid request encoding.")?;
    if body.len() > LIMIT {
        return Err("The local request is too large.".into());
    }
    if service.kind == Kind::Model {
        let value: Value = serde_json::from_slice(&body).map_err(|_| "Invalid model request.")?;
        if value.get("model").and_then(Value::as_str) != service.model.as_deref() {
            return Err("This model was not approved.".into());
        }
    }
    let client = reqwest::Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .map_err(|e| e.to_string())?;
    let mut request = client.request(
        method.parse().map_err(|_| "Invalid method.")?,
        format!("{}{suffix}", service.endpoint),
    );
    if let Some(headers) = args.get("headers").and_then(Value::as_object) {
        for name in [
            "content-type",
            "accept",
            "mcp-session-id",
            "mcp-protocol-version",
            "last-event-id",
        ] {
            if let Some(value) = headers.get(name).and_then(Value::as_str) {
                request = request.header(name, value);
            }
        }
    }
    let mut response = request
        .body(body)
        .send()
        .await
        .map_err(|_| "The local service could not be reached.")?;
    let status = response.status().as_u16();
    let mut headers = Map::new();
    for name in ["content-type", "mcp-session-id", "mcp-protocol-version"] {
        if let Some(value) = response.headers().get(name).and_then(|v| v.to_str().ok()) {
            headers.insert(name.into(), value.into());
        }
    }
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "The local service stopped answering.")?
    {
        if body.len() + chunk.len() > LIMIT {
            return Err("The local service's answer is too large.".into());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(serde_json::from_value(serde_json::json!({"status":status,"headers":headers,"body":base64::engine::general_purpose::STANDARD.encode(body)})).map_err(|e| e.to_string())?)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn model(endpoint: &str) -> Service {
        Service {
            id: "ollama".into(),
            name: "Ollama".into(),
            kind: Kind::Model,
            endpoint: endpoint.into(),
            model: Some("local-model".into()),
        }
    }
    #[test]
    fn only_literal_loopback_without_credentials_is_accepted() {
        assert_eq!(
            checked(model("http://localhost:11434/v1")).unwrap().endpoint,
            "http://127.0.0.1:11434/v1"
        );
        assert!(checked(model("http://[::1]:1234/v1")).is_ok());
        for address in [
            "http://example.com",
            "http://127.0.0.2",
            "http://user:secret@127.0.0.1",
            "file:///etc/passwd",
            "http://127.0.0.1/?token=secret",
        ] {
            assert!(checked(model(address)).is_err(), "{address}");
        }
    }
    #[test]
    fn a_model_must_be_explicitly_named() {
        let mut service = model("http://127.0.0.1:11434/v1");
        service.model = None;
        assert!(checked(service).is_err());
    }
}
