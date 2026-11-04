//! The computer as a device: what the desktop app and the server say to each other (#2305).
//!
//! The app holds one outbound WebSocket to the server's device hub, opened with
//! the app's own session, and the person's runs reach this computer through it.
//! This module is the part both sides must agree on - the frames, where the
//! socket is, how long to wait before trying again - kept free of the runtime so
//! it can be tested on its own.

use std::time::Duration;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use url::Url;

use crate::is_loopback;

/// Where a deployment's API and sockets answer, as its console reported them.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Endpoints {
    pub api: Url,
    pub ws: Url,
}

/// The console's `/api/public/endpoints` answer.
#[derive(Debug, Deserialize)]
pub struct EndpointsAnswer {
    pub api_url: String,
    pub ws_url: String,
}

impl Endpoints {
    /// Where the console asks: its own origin, whatever path the app opened it at.
    pub fn discovery_url(server: &Url) -> Url {
        let mut url = server.clone();
        url.set_path("/api/public/endpoints");
        url.set_query(None);
        url.set_fragment(None);
        url
    }

    /// Read and check the console's answer.
    ///
    /// The API carries the device's tokens and the socket carries what the
    /// server asks this computer to do, so both are held to the rule a typed
    /// server address is: encrypted, unless the server is this machine.
    pub fn from_answer(answer: &EndpointsAnswer) -> Result<Self, String> {
        let api = Url::parse(&answer.api_url)
            .map_err(|_| "The server named no valid API address.".to_owned())?;
        let ws = Url::parse(&answer.ws_url)
            .map_err(|_| "The server named no valid socket address.".to_owned())?;
        let local = |url: &Url| url.host_str().is_some_and(is_loopback);
        match api.scheme() {
            "https" => {}
            "http" if local(&api) => {}
            _ => return Err("The server's API is not on an encrypted address.".to_owned()),
        }
        match ws.scheme() {
            "wss" => {}
            "ws" if local(&ws) => {}
            _ => return Err("The server's sockets are not on an encrypted address.".to_owned()),
        }
        Ok(Self { api, ws })
    }

    /// An API route, at the API's origin.
    pub fn api_route(&self, path: &str) -> Url {
        let mut url = self.api.clone();
        url.set_path(path);
        url.set_query(None);
        url
    }

    /// The device hub's socket.
    pub fn device_socket(&self) -> Url {
        let mut url = self.ws.clone();
        url.set_path("/api/v1/ws/device");
        url.set_query(None);
        url
    }
}

/// What the server sends down the socket.
#[derive(Debug, Clone, PartialEq, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerFrame {
    /// Run one operation and answer with a [`AppFrame::Result`] of the same id.
    Call {
        id: String,
        op: String,
        #[serde(default)]
        args: Map<String, Value>,
    },
    /// The caller gave up on a call: stop it, and answer nothing.
    Cancel { id: String },
}

/// What this computer can do, as the server lists it.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Capabilities {
    /// The local sandbox's modes this OS supports; empty while it has none.
    pub sandbox_modes: Vec<&'static str>,
    /// Whether screen capture and input are available (permissions granted).
    pub screen: bool,
}

/// What the app sends up the socket.
#[derive(Debug, Clone, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum AppFrame {
    Hello {
        version: String,
        capabilities: Capabilities,
    },
    Result {
        id: String,
        ok: bool,
        value: Map<String, Value>,
        #[serde(skip_serializing_if = "Option::is_none")]
        error: Option<String>,
        /// What sort of refusal, so the server raises the error a tool expects.
        #[serde(skip_serializing_if = "Option::is_none")]
        kind: Option<String>,
    },
    Ping,
}

impl AppFrame {
    /// A call's answer: its value, or the sentence saying why not and its kind.
    pub fn answer(id: String, outcome: Result<Map<String, Value>, (String, &str)>) -> Self {
        match outcome {
            Ok(value) => AppFrame::Result {
                id,
                ok: true,
                value,
                error: None,
                kind: None,
            },
            Err((error, kind)) => AppFrame::Result {
                id,
                ok: false,
                value: Map::new(),
                error: Some(error),
                kind: Some(kind.to_owned()),
            },
        }
    }
}

/// How long to wait before reconnecting after `failures` failed attempts in a row.
///
/// Doubling from one second to a minute: a laptop waking from sleep reconnects at
/// once, and a server that is down is not hammered.
pub fn backoff(failures: u32) -> Duration {
    Duration::from_secs(1u64 << failures.min(6)).min(Duration::from_secs(60))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn answer(api: &str, ws: &str) -> EndpointsAnswer {
        EndpointsAnswer {
            api_url: api.to_owned(),
            ws_url: ws.to_owned(),
        }
    }

    #[test]
    fn the_console_is_asked_at_its_own_origin() {
        let server = Url::parse("https://console.acme.test/chat?x=1#top").unwrap();
        assert_eq!(
            Endpoints::discovery_url(&server).as_str(),
            "https://console.acme.test/api/public/endpoints"
        );
    }

    #[test]
    fn encrypted_endpoints_are_taken_and_routes_are_built_on_them() {
        let endpoints =
            Endpoints::from_answer(&answer("https://api.acme.test", "wss://api.acme.test"))
                .unwrap();
        assert_eq!(
            endpoints.device_socket().as_str(),
            "wss://api.acme.test/api/v1/ws/device"
        );
        assert_eq!(
            endpoints.api_route("/api/v1/auth/refresh").as_str(),
            "https://api.acme.test/api/v1/auth/refresh"
        );
    }

    #[test]
    fn plain_endpoints_are_taken_only_on_this_machine() {
        assert!(
            Endpoints::from_answer(&answer("http://localhost:8000", "ws://localhost:8000")).is_ok()
        );
        assert!(
            Endpoints::from_answer(&answer("http://api.acme.test", "wss://api.acme.test")).is_err()
        );
        assert!(
            Endpoints::from_answer(&answer("https://api.acme.test", "ws://api.acme.test")).is_err()
        );
        assert!(Endpoints::from_answer(&answer("not a url", "wss://api.acme.test")).is_err());
        assert!(Endpoints::from_answer(&answer("https://api.acme.test", "ftp://x")).is_err());
    }

    #[test]
    fn a_call_and_a_cancel_are_read_and_anything_else_is_refused() {
        let call: ServerFrame = serde_json::from_value(
            json!({"type": "call", "id": "a", "op": "fs.read", "args": {"path": "x"}}),
        )
        .unwrap();
        assert_eq!(
            call,
            ServerFrame::Call {
                id: "a".into(),
                op: "fs.read".into(),
                args: json!({"path": "x"}).as_object().unwrap().clone(),
            }
        );
        let cancel: ServerFrame =
            serde_json::from_value(json!({"type": "cancel", "id": "a"})).unwrap();
        assert_eq!(cancel, ServerFrame::Cancel { id: "a".into() });
        assert!(serde_json::from_value::<ServerFrame>(json!({"type": "launch"})).is_err());
    }

    #[test]
    fn frames_go_up_in_the_shape_the_hub_reads() {
        let hello = AppFrame::Hello {
            version: "0.3.0".into(),
            capabilities: Capabilities {
                sandbox_modes: vec!["read_only"],
                screen: false,
            },
        };
        assert_eq!(
            serde_json::to_value(&hello).unwrap(),
            json!({"type": "hello", "version": "0.3.0", "capabilities": {"sandbox_modes": ["read_only"], "screen": false}})
        );
        assert_eq!(
            serde_json::to_value(AppFrame::answer(
                "a".into(),
                Err(("No such file".into(), "not_found"))
            ))
            .unwrap(),
            json!({"type": "result", "id": "a", "ok": false, "value": {}, "error": "No such file", "kind": "not_found"})
        );
        assert_eq!(
            serde_json::to_value(AppFrame::answer("b".into(), Ok(Map::new()))).unwrap(),
            json!({"type": "result", "id": "b", "ok": true, "value": {}})
        );
        assert_eq!(
            serde_json::to_value(AppFrame::Ping).unwrap(),
            json!({"type": "ping"})
        );
    }

    #[test]
    fn reconnecting_backs_off_to_a_minute() {
        assert_eq!(backoff(0), Duration::from_secs(1));
        assert_eq!(backoff(3), Duration::from_secs(8));
        assert_eq!(backoff(6), Duration::from_secs(60));
        assert_eq!(backoff(40), Duration::from_secs(60));
    }
}
