//! Persistent local authority is narrower than an interactive folder grant.
//!
//! Each consent belongs to one paired device session, person, server,
//! organization and routine. Replacing a consent creates a fresh ID; a queued
//! or parked run cannot borrow the replacement.

use base64::Engine;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use uuid::Uuid;

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DeviceIdentity {
    pub origin: String,
    pub user_id: Uuid,
    pub device_id: Uuid,
}

/// Keychain metadata bound to the exact credential, without changing the raw
/// refresh-token entry older desktop versions already understand.
#[derive(Deserialize, Serialize)]
pub struct StoredDeviceIdentity {
    pub identity: DeviceIdentity,
    credential_fingerprint: String,
}

impl StoredDeviceIdentity {
    pub fn new(origin: String, access: &str, refresh: &str) -> Result<Self, &'static str> {
        Ok(Self {
            identity: DeviceIdentity::from_access_token(origin, access)?,
            credential_fingerprint: format!("{:x}", Sha256::digest(refresh.as_bytes())),
        })
    }

    pub fn matches(&self, refresh: &str) -> bool {
        self.credential_fingerprint == format!("{:x}", Sha256::digest(refresh.as_bytes()))
    }
}

impl DeviceIdentity {
    /// Extract identity from the access token returned directly by our paired
    /// server. This is not JWT verification: the server authenticates the socket.
    /// Refresh tokens have no session ID and cannot supply this identity.
    pub fn from_access_token(origin: String, token: &str) -> Result<Self, &'static str> {
        #[derive(Deserialize)]
        struct Claims {
            sub: Uuid,
            sid: Uuid,
            #[serde(rename = "type")]
            kind: String,
        }
        let mut parts = token.split('.');
        let header = parts.next();
        let body = parts.next().ok_or("The device session has no identity")?;
        if header == Some("") || parts.next().is_none() || parts.next().is_some() {
            return Err("The device session has no identity");
        }
        let bytes = base64::engine::general_purpose::URL_SAFE_NO_PAD
            .decode(body)
            .map_err(|_| "The device session has no identity")?;
        let claims: Claims =
            serde_json::from_slice(&bytes).map_err(|_| "The device session has no identity")?;
        if claims.kind != "access" || claims.sub.is_nil() || claims.sid.is_nil() {
            return Err("The device session has no identity");
        }
        Ok(Self {
            origin,
            user_id: claims.sub,
            device_id: claims.sid,
        })
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Operations {
    pub read: bool,
    pub write: bool,
    pub execute: bool,
}

impl Operations {
    pub fn validate(self) -> Result<(), &'static str> {
        if !self.read || (self.execute && !self.write) {
            return Err("Local execution requires read and write access; every folder grant needs read access");
        }
        Ok(())
    }

    pub fn contains(self, requested: Self) -> bool {
        (!requested.read || self.read)
            && (!requested.write || self.write)
            && (!requested.execute || self.execute)
    }

    fn allows(self, op: &str) -> bool {
        match op {
            "routine.check" => true,
            "fs.read" | "fs.stat" | "fs.list" | "fs.exists" | "fs.realpath" => self.read,
            "fs.write" | "fs.mkdir" | "fs.remove" => self.write,
            "shell.run" => self.execute,
            _ => false,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RoutineScope {
    pub grant_id: Uuid,
    pub organization_id: Uuid,
    pub routine_id: Uuid,
    pub user_id: Uuid,
    pub device_id: Uuid,
    pub operations: Operations,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum WorkContext {
    Interactive,
    Routine(RoutineScope),
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RoutineGrant {
    pub id: Uuid,
    pub identity: DeviceIdentity,
    pub organization_id: Uuid,
    pub routine_id: Uuid,
    pub name: String,
    pub root: String,
    pub operations: Operations,
}

impl RoutineGrant {
    pub fn authorize(
        &self,
        identity: &DeviceIdentity,
        scope: &RoutineScope,
        root: &str,
        op: &str,
    ) -> Result<(), &'static str> {
        self.operations.validate()?;
        scope.operations.validate()?;
        if self.id != scope.grant_id
            || &self.identity != identity
            || scope.user_id != identity.user_id
            || scope.device_id != identity.device_id
            || self.organization_id != scope.organization_id
            || self.routine_id != scope.routine_id
            || self.root != root
            || !self.operations.contains(scope.operations)
            || !scope.operations.allows(op)
        {
            return Err(
                "This routine has no current consent for that folder operation on this device",
            );
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn granted() -> (RoutineGrant, RoutineScope) {
        let identity = DeviceIdentity {
            origin: "https://console.example.com".into(),
            user_id: Uuid::new_v4(),
            device_id: Uuid::new_v4(),
        };
        let grant = RoutineGrant {
            id: Uuid::new_v4(),
            identity,
            organization_id: Uuid::new_v4(),
            routine_id: Uuid::new_v4(),
            name: "Prepare reports".into(),
            root: "/work/reports".into(),
            operations: Operations {
                read: true,
                write: true,
                execute: true,
            },
        };
        let scope = RoutineScope {
            grant_id: grant.id,
            organization_id: grant.organization_id,
            routine_id: grant.routine_id,
            user_id: grant.identity.user_id,
            device_id: grant.identity.device_id,
            operations: grant.operations,
        };
        (grant, scope)
    }

    #[test]
    fn every_identity_dimension_is_required_and_regrant_cannot_release_parked_work() {
        let (grant, scope) = granted();
        assert!(grant
            .authorize(&grant.identity, &scope, &grant.root, "shell.run")
            .is_ok());
        for changed in [
            RoutineScope {
                grant_id: Uuid::new_v4(),
                ..scope.clone()
            },
            RoutineScope {
                organization_id: Uuid::new_v4(),
                ..scope.clone()
            },
            RoutineScope {
                routine_id: Uuid::new_v4(),
                ..scope.clone()
            },
            RoutineScope {
                user_id: Uuid::new_v4(),
                ..scope.clone()
            },
            RoutineScope {
                device_id: Uuid::new_v4(),
                ..scope.clone()
            },
        ] {
            assert!(grant
                .authorize(&grant.identity, &changed, &grant.root, "fs.read")
                .is_err());
        }
        let mut elsewhere = grant.identity.clone();
        elsewhere.origin = "https://elsewhere.example.com".into();
        assert!(grant
            .authorize(&elsewhere, &scope, &grant.root, "fs.read")
            .is_err());
        assert!(grant
            .authorize(&grant.identity, &scope, "/work/other", "fs.read")
            .is_err());
    }

    #[test]
    fn read_write_and_execute_are_separate_and_scope_can_only_narrow() {
        let (grant, mut scope) = granted();
        scope.operations = Operations {
            read: true,
            write: false,
            execute: false,
        };
        assert!(grant
            .authorize(&grant.identity, &scope, &grant.root, "fs.read")
            .is_ok());
        for op in [
            "fs.write",
            "fs.mkdir",
            "fs.remove",
            "shell.run",
            "screen.capture",
            "browser.open",
        ] {
            assert!(grant
                .authorize(&grant.identity, &scope, &grant.root, op)
                .is_err());
        }
        scope.operations.write = true;
        assert!(grant
            .authorize(&grant.identity, &scope, &grant.root, "fs.write")
            .is_ok());
        assert!(grant
            .authorize(&grant.identity, &scope, &grant.root, "shell.run")
            .is_err());
        let mut read_only = grant.clone();
        read_only.operations = Operations {
            read: true,
            write: false,
            execute: false,
        };
        assert!(read_only
            .authorize(&grant.identity, &scope, &grant.root, "routine.check")
            .is_err());
    }

    #[test]
    fn shell_cannot_be_mistaken_for_a_read_only_operation() {
        assert!(Operations {
            read: true,
            write: false,
            execute: true
        }
        .validate()
        .is_err());
        assert!(Operations {
            read: false,
            write: true,
            execute: false
        }
        .validate()
        .is_err());
    }

    #[test]
    fn only_access_token_session_identity_is_kept_and_never_the_token() {
        let user = Uuid::new_v4();
        let device = Uuid::new_v4();
        let payload = serde_json::json!({"sub": user.to_string(), "sid": device.to_string(), "type": "access"});
        let token = format!(
            "header.{}.signature",
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(payload.to_string())
        );
        let identity =
            DeviceIdentity::from_access_token("https://console.example.com".into(), &token)
                .unwrap();
        assert_eq!(identity.user_id, user);
        assert_eq!(identity.device_id, device);
        assert!(!serde_json::to_string(&identity).unwrap().contains(&token));
        let metadata =
            StoredDeviceIdentity::new(identity.origin.clone(), &token, "first-refresh").unwrap();
        assert!(metadata.matches("first-refresh"));
        assert!(!metadata.matches("next-refresh"));
        assert!(!serde_json::to_string(&metadata)
            .unwrap()
            .contains("first-refresh"));
        for invalid in [
            "opaque",
            "header.e30.signature",
            "header.eyJ0eXBlIjoicmVmcmVzaCJ9.signature",
        ] {
            assert!(DeviceIdentity::from_access_token(
                "https://console.example.com".into(),
                invalid
            )
            .is_err());
        }
    }

    #[test]
    fn missing_legacy_context_or_unknown_scope_is_never_interactive() {
        assert!(serde_json::from_value::<WorkContext>(serde_json::Value::Null).is_err());
        assert!(
            serde_json::from_value::<WorkContext>(serde_json::json!({"kind":"other"})).is_err()
        );
        assert_eq!(
            serde_json::from_value::<WorkContext>(serde_json::json!({"kind":"interactive"}))
                .unwrap(),
            WorkContext::Interactive
        );
        let (_, scope) = granted();
        let value = serde_json::to_value(WorkContext::Routine(scope.clone())).unwrap();
        assert_eq!(
            serde_json::from_value::<WorkContext>(value).unwrap(),
            WorkContext::Routine(scope)
        );
    }
}
