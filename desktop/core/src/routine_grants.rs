//! Persistent local authority is narrower than an interactive folder grant.
//!
//! Each consent belongs to a person, server and organization on this computer.
//! One-routine grants also bind the paired session; all-routine grants survive
//! that person's new sessions. Replacing a consent creates a fresh ID; queued
//! or parked work cannot borrow the replacement.

use std::path::{Component, Path, PathBuf};

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
    /// One routine, or `None` for every routine of this person in this
    /// organization: the person said once that their routines may work here.
    #[serde(default)]
    pub routine_id: Option<Uuid>,
    pub name: String,
    pub root: String,
    pub operations: Operations,
}

/// Validate a local, absolute root without touching the filesystem. Windows
/// network/device prefixes must never trigger authentication before authorization.
pub fn local_root(root: &Path) -> Result<PathBuf, &'static str> {
    if !root.is_absolute() || root.components().any(|part| part == Component::ParentDir) {
        return Err("Routine folders must be absolute local paths without parent traversal");
    }
    #[cfg(windows)]
    {
        use std::path::Prefix;

        let mut parts = root.components();
        let drive = match parts.next() {
            Some(Component::Prefix(prefix)) => match prefix.kind() {
                Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
                _ => return Err("Routine folders cannot use network or device paths"),
            },
            _ => return Err("Routine folders must name a local drive"),
        };
        // Canonical Windows paths use a verbatim disk prefix; compare them with
        // ordinary drive paths without resolving an untrusted root first.
        let mut local = PathBuf::from(format!("{}:\\", char::from(drive.to_ascii_uppercase())));
        for part in parts {
            match part {
                Component::RootDir | Component::CurDir => (),
                Component::Normal(name) if name != ".." => local.push(name),
                _ => return Err("Routine folders cannot use parent traversal"),
            }
        }
        Ok(local)
    }
    #[cfg(not(windows))]
    {
        Ok(root.to_path_buf())
    }
}

impl RoutineGrant {
    /// Regranting one routine revokes its old authority. A grant shared by all
    /// routines stays addressable until explicitly revoked, even at the same root.
    pub fn replaces(&self, old: &Self) -> bool {
        self.routine_id.is_some()
            && self.routine_id == old.routine_id
            && self.identity.origin == old.identity.origin
            && self.identity.user_id == old.identity.user_id
            && self.organization_id == old.organization_id
    }

    /// Check identity, operations and lexical containment without filesystem I/O.
    /// The caller must open the returned root without following links before use;
    /// resolving either the grant or request first could retarget its authority.
    pub fn authorize(
        &self,
        identity: &DeviceIdentity,
        scope: &RoutineScope,
        root: &str,
        op: &str,
    ) -> Result<PathBuf, &'static str> {
        self.operations.validate()?;
        scope.operations.validate()?;
        // A grant for every routine is the person's, on this computer, wherever
        // they are signed in to it: a new session after signing in again keeps it.
        // A grant for one routine stays bound to the session that approved it.
        let same_person = match self.routine_id {
            Some(_) => &self.identity == identity,
            None => {
                self.identity.origin == identity.origin && self.identity.user_id == identity.user_id
            }
        };
        let routine_matches = self.routine_id.map_or(true, |id| id == scope.routine_id);
        let root_matches = self.routine_id.is_none() || self.root == root;
        if self.id != scope.grant_id
            || !same_person
            || scope.user_id != identity.user_id
            || scope.device_id != identity.device_id
            || self.organization_id != scope.organization_id
            || !routine_matches
            || !root_matches
            || !self.operations.contains(scope.operations)
            || !scope.operations.allows(op)
        {
            return Err(
                "This routine has no current consent for that folder operation on this device",
            );
        }
        if self.routine_id.is_none() {
            let approved = local_root(Path::new(&self.root))?;
            let requested = local_root(Path::new(root))?;
            if !requested.starts_with(&approved) {
                return Err("The routine folder is outside its approved folder");
            }
        }
        Ok(PathBuf::from(root))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestFolder(PathBuf);

    impl TestFolder {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!("routine-grants-{}", Uuid::new_v4()));
            std::fs::create_dir_all(root.join("reports/q3")).unwrap();
            std::fs::create_dir_all(root.join("outside")).unwrap();
            Self(root.canonicalize().unwrap())
        }
    }

    impl Drop for TestFolder {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

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
            routine_id: Some(Uuid::new_v4()),
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
            routine_id: grant.routine_id.unwrap(),
            user_id: grant.identity.user_id,
            device_id: grant.identity.device_id,
            operations: grant.operations,
        };
        (grant, scope)
    }

    #[test]
    fn approving_another_root_or_stronger_operations_keeps_existing_routines_authorized() {
        let folder = TestFolder::new();
        let (mut old, mut scope) = granted();
        old.routine_id = None;
        old.root = folder.0.join("reports").to_string_lossy().into_owned();
        old.operations = Operations {
            read: true,
            write: false,
            execute: false,
        };
        scope.operations = old.operations;
        for root in [
            old.root.clone(),
            folder.0.join("outside").to_string_lossy().into_owned(),
        ] {
            let mut added = old.clone();
            added.id = Uuid::new_v4();
            added.root = root;
            added.operations = Operations {
                read: true,
                write: true,
                execute: true,
            };
            let mut grants = vec![old.clone()];
            grants.retain(|grant| !added.replaces(grant));
            grants.push(added);
            let existing = grants
                .iter()
                .find(|grant| grant.id == scope.grant_id)
                .unwrap();
            assert!(existing
                .authorize(&old.identity, &scope, &old.root, "fs.read")
                .is_ok());
            assert_eq!(grants.len(), 2);
        }
    }

    #[test]
    fn only_a_new_grant_for_the_same_person_and_routine_replaces_old_authority() {
        let (old, _) = granted();
        let mut added = old.clone();
        added.id = Uuid::new_v4();
        added.identity.device_id = Uuid::new_v4();
        assert!(added.replaces(&old));
        let mut other = old.clone();
        other.organization_id = Uuid::new_v4();
        assert!(!added.replaces(&other));
        other = old.clone();
        other.identity.user_id = Uuid::new_v4();
        assert!(!added.replaces(&other));
        other = old.clone();
        other.identity.origin = "https://other.example".into();
        assert!(!added.replaces(&other));
        other = old.clone();
        other.routine_id = Some(Uuid::new_v4());
        assert!(!added.replaces(&other));
        added.routine_id = None;
        assert!(!added.replaces(&old));
    }

    #[test]
    fn an_outside_root_is_refused_before_filesystem_resolution() {
        let folder = TestFolder::new();
        let (mut grant, scope) = granted();
        grant.routine_id = None;
        grant.root = folder.0.join("reports").to_string_lossy().into_owned();
        let missing = folder.0.join("not-created");
        assert_eq!(
            grant.authorize(
                &grant.identity,
                &scope,
                missing.to_str().unwrap(),
                "fs.read"
            ),
            Err("The routine folder is outside its approved folder")
        );
    }

    #[cfg(windows)]
    #[test]
    fn windows_network_and_device_roots_are_refused_without_filesystem_access() {
        let (mut grant, scope) = granted();
        grant.routine_id = None;
        grant.root = r"C:\not-created-routine-folder".into();
        for root in [
            r"\\attacker\share",
            r"\\?\UNC\attacker\share",
            r"\\.\C:\work",
            r"\\?\GLOBALROOT\Device\Mup\attacker\share",
            "//attacker/share",
        ] {
            assert_eq!(
                local_root(Path::new(root)),
                Err("Routine folders cannot use network or device paths"),
                "accepted {root}"
            );
            assert_eq!(
                grant.authorize(&grant.identity, &scope, root, "fs.read"),
                Err("Routine folders cannot use network or device paths")
            );
        }
        assert_eq!(
            local_root(Path::new(r"\\?\C:\work")).unwrap(),
            PathBuf::from(r"C:\work")
        );
        assert_eq!(
            local_root(Path::new(r"c:\work")).unwrap(),
            PathBuf::from(r"C:\work")
        );
        assert!(local_root(Path::new(r"C:\work\..\outside")).is_err());
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
    fn a_grant_for_every_routine_covers_its_folder_and_survives_a_new_session() {
        let (mut grant, scope) = granted();
        grant.routine_id = None;
        let folder = TestFolder::new();
        grant.root = folder.0.join("reports").to_string_lossy().into_owned();
        let child = folder.0.join("reports/q3");
        let other_routine = RoutineScope {
            routine_id: Uuid::new_v4(),
            ..scope.clone()
        };
        assert!(grant
            .authorize(
                &grant.identity,
                &other_routine,
                child.to_str().unwrap(),
                "fs.read"
            )
            .is_ok());
        // Signed in again: a new session, the same person on the same server.
        let mut again = grant.identity.clone();
        again.device_id = Uuid::new_v4();
        let rebound = RoutineScope {
            device_id: again.device_id,
            ..scope.clone()
        };
        assert!(grant
            .authorize(&again, &rebound, &grant.root, "fs.read")
            .is_ok());
        for (identity, root) in [
            (
                DeviceIdentity {
                    user_id: Uuid::new_v4(),
                    ..again.clone()
                },
                grant.root.as_str(),
            ),
            (
                DeviceIdentity {
                    origin: "https://elsewhere.example.com".into(),
                    ..again.clone()
                },
                grant.root.as_str(),
            ),
            (again.clone(), "/work/reports-old"),
            (again.clone(), "/work"),
        ] {
            let scope = RoutineScope {
                device_id: identity.device_id,
                user_id: identity.user_id,
                ..scope.clone()
            };
            assert!(grant.authorize(&identity, &scope, root, "fs.read").is_err());
        }
    }

    #[test]
    fn all_routine_roots_cannot_escape_through_parent_components() {
        let folder = TestFolder::new();
        let (mut grant, scope) = granted();
        grant.routine_id = None;
        grant.root = folder.0.join("reports").to_string_lossy().into_owned();
        let escape = Path::new(&grant.root).join("../outside");
        assert!(grant
            .authorize(
                &grant.identity,
                &scope,
                escape.to_str().unwrap(),
                "shell.run"
            )
            .is_err());
    }

    #[test]
    fn lexical_authorization_does_not_resolve_or_require_a_filesystem_root() {
        let folder = TestFolder::new();
        let (mut grant, scope) = granted();
        grant.routine_id = None;
        grant.root = folder.0.join("not-created").to_string_lossy().into_owned();
        let requested = Path::new(&grant.root).join("child");
        assert_eq!(
            grant
                .authorize(
                    &grant.identity,
                    &scope,
                    requested.to_str().unwrap(),
                    "fs.read"
                )
                .unwrap(),
            requested
        );
    }

    #[test]
    fn a_grant_from_an_older_app_still_names_its_routine() {
        let (grant, _) = granted();
        let stored = serde_json::to_value(&grant).unwrap();
        let read: RoutineGrant = serde_json::from_value(stored).unwrap();
        assert_eq!(read.routine_id, grant.routine_id);
        let mut legacy = serde_json::to_value(&grant).unwrap();
        legacy["routine_id"] = serde_json::Value::String(grant.routine_id.unwrap().to_string());
        assert_eq!(
            serde_json::from_value::<RoutineGrant>(legacy).unwrap(),
            grant
        );
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
