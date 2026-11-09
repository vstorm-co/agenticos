//! Native, persistent consent for one routine's bounded folder operations.

use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use agenticos_shell_core::routine_grants::{
    local_root, DeviceIdentity, Operations, RoutineGrant, RoutineScope, WorkContext,
};
use serde::Deserialize;
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use uuid::Uuid;

#[derive(Default)]
pub struct Access(Mutex<()>);

const MAX_GRANTS: usize = 256;
const MAX_STORE_BYTES: u64 = 4 * 1024 * 1024;

/// The current store fingerprint lives in the OS credential service, separate
/// from the writable permission JSON. Changing JSON or replaying
/// an earlier, revoked store cannot manufacture native approval.
trait StoreAuthority {
    fn read(&self) -> Result<Option<String>, String>;
    fn write(&self, fingerprint: &str) -> Result<(), String>;
}

impl StoreAuthority for keyring::Entry {
    fn read(&self) -> Result<Option<String>, String> {
        match self.get_password() {
            Ok(value) => Ok(Some(value)),
            Err(keyring::Error::NoEntry) => Ok(None),
            Err(_) => Err("The keychain cannot verify routine permissions".into()),
        }
    }

    fn write(&self, fingerprint: &str) -> Result<(), String> {
        self.set_password(fingerprint)
            .map_err(|_| "The keychain cannot authenticate routine permissions".into())
    }
}

struct Store<A> {
    path: PathBuf,
    authority: A,
}

fn fingerprint(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn store(app: &AppHandle) -> Result<Store<keyring::Entry>, String> {
    let path = app
        .path()
        .app_config_dir()
        .map(|path| path.join("routine-access.json"))
        .map_err(|_| "The routine permission store is unavailable".to_owned())?;
    let account = format!("routine-permissions:{}", fingerprint(path.to_string_lossy().as_bytes()));
    let authority = keyring::Entry::new("AgenticOS", &account)
        .map_err(|_| "The routine permission keychain is unavailable".to_owned())?;
    Ok(Store { path, authority })
}

impl<A: StoreAuthority> Store<A> {
    fn load(&self) -> Result<Vec<RoutineGrant>, String> {
        let file = match File::open(&self.path) {
            Ok(file) => file,
            Err(error) if error.kind() == ErrorKind::NotFound => return Ok(Vec::new()),
            Err(_) => return Err("Cannot read routine permissions".into()),
        };
        let mut bytes = Vec::new();
        file.take(MAX_STORE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| "Cannot read routine permissions".to_owned())?;
        if bytes.len() as u64 > MAX_STORE_BYTES {
            return Err("The routine permission store exceeds its size limit".into());
        }
        let expected = self.authority.read()?;
        if expected.as_deref() != Some(fingerprint(&bytes).as_str()) {
            return Err("Routine permissions are unverified or changed; unlink this computer, link it again and approve the routines again".into());
        }
        let grants: Vec<RoutineGrant> = serde_json::from_slice(&bytes)
            .map_err(|_| "Cannot read routine permissions; no routine access is allowed".to_owned())?;
        if grants.len() > MAX_GRANTS {
            return Err("The routine permission store exceeds its grant limit".into());
        }
        Ok(grants)
    }

    fn save(&self, grants: &[RoutineGrant]) -> Result<(), String> {
        let path = &self.path;
        let parent = path.parent().ok_or("The routine permission store is unavailable")?;
        fs::create_dir_all(parent).map_err(|_| "Cannot create the routine permission store".to_owned())?;
        let pending = path.with_extension(format!("{}.pending", Uuid::new_v4()));
        let written = (|| {
            let bytes = serde_json::to_vec(grants).map_err(|_| "Cannot encode routine permissions".to_owned())?;
            let mut options = OpenOptions::new();
            options.write(true).create_new(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::OpenOptionsExt;
                options.mode(0o600);
            }
            let mut file = options
                .open(&pending)
                .map_err(|_| "Cannot save routine permissions".to_owned())?;
            file.write_all(&bytes)
                .map_err(|_| "Cannot save routine permissions".to_owned())?;
            file.sync_all()
                .map_err(|_| "Cannot persist routine permissions".to_owned())?;
            drop(file);
            // Pin the new content outside the filesystem before publishing it. A
            // crash or failed rename leaves no matching authority and fails closed.
            self.authority.write(&fingerprint(&bytes))?;
            fs::rename(&pending, path).map_err(|_| "Cannot replace routine permissions".to_owned())?;
            #[cfg(unix)]
            File::open(parent)
                .and_then(|directory| directory.sync_all())
                .map_err(|_| "Cannot persist the routine permission directory".to_owned())?;
            Ok(())
        })();
        if pending.exists() && fs::remove_file(&pending).is_err() {
            eprintln!("Could not remove an incomplete routine permission write");
        }
        written
    }
}

pub fn clear(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    store(app)?.save(&[])
}

/// Keep owner-bound shared grants dormant while no device session is active.
/// A verified new identity narrows them again before its connection starts.
pub fn retain_shared(app: &AppHandle, identity: Option<&DeviceIdentity>) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    retain_shared_at(&store(app)?, identity)
}

fn retain_shared_at(store: &Store<impl StoreAuthority>, identity: Option<&DeviceIdentity>) -> Result<(), String> {
    let mut grants = store.load()?;
    grants.retain(|grant| {
        grant.routine_id.is_none()
            && match identity {
                Some(identity) => owns(grant, identity),
                None => true,
            }
    });
    // Filter the current store rather than restoring a snapshot: a concurrent
    // explicit revocation must never be resurrected during pairing.
    store.save(&grants)
}

pub fn revoke_folder(app: &AppHandle, root: &str) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    let store = store(app)?;
    let mut grants = store.load()?;
    grants.retain(|grant| grant.root != root);
    store.save(&grants)
}

/// Whether this signed-in person holds `grant`: a grant for every routine is
/// theirs on any session of this server; a grant for one routine, on the
/// session that approved it.
fn owns(grant: &RoutineGrant, identity: &DeviceIdentity) -> bool {
    grant.identity.origin == identity.origin
        && grant.identity.user_id == identity.user_id
        && (grant.routine_id.is_none() || &grant.identity == identity)
}

#[tauri::command]
pub fn routine_grants(app: AppHandle, organization_id: Uuid, user_id: Uuid) -> Result<Vec<RoutineGrant>, String> {
    let identity = crate::device::identity(&app)?;
    if identity.user_id != user_id {
        return Err("This computer is linked to another account".into());
    }
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    Ok(store(&app)?
        .load()?
        .into_iter()
        .filter(|grant| owns(grant, &identity) && grant.organization_id == organization_id)
        .collect())
}

#[tauri::command]
pub fn routine_revoke(app: AppHandle, id: Uuid, organization_id: Uuid, user_id: Uuid) -> Result<(), String> {
    let identity = crate::device::identity(&app)?;
    if identity.user_id != user_id {
        return Err("This computer is linked to another account".into());
    }
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    let store = store(&app)?;
    let mut grants = store.load()?;
    grants.retain(|grant| grant.id != id || !owns(grant, &identity) || grant.organization_id != organization_id);
    store.save(&grants)
}

#[tauri::command]
pub async fn routine_choose_folder(app: AppHandle) -> Result<Option<String>, String> {
    crate::device::identity(&app)?;
    let (picked, answer) = tokio::sync::oneshot::channel();
    app.dialog()
        .file()
        .set_title("Choose the folder for this routine")
        .pick_folder(move |folder| {
            let _ = picked.send(folder);
        });
    let Some(folder) = answer.await.ok().flatten() else {
        return Ok(None);
    };
    let path = folder
        .into_path()
        .map_err(|_| "That folder is not available".to_owned())?;
    let canonical = fs::canonicalize(path).map_err(|_| "That folder is not available".to_owned())?;
    if !canonical.is_dir() {
        return Err("Choose a folder".into());
    }
    Ok(Some(canonical.to_string_lossy().into_owned()))
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    organization_id: Uuid,
    /// One routine, or none for every routine of this person.
    #[serde(default)]
    routine_id: Option<Uuid>,
    user_id: Uuid,
    device_id: Uuid,
    name: String,
    root: String,
    operations: Operations,
}

#[tauri::command]
pub async fn routine_allow(app: AppHandle, request: Request) -> Result<Option<RoutineGrant>, String> {
    let _transition = crate::device::transition(&app).await;
    let identity = crate::device::identity(&app)?;
    if request.user_id != identity.user_id || request.device_id != identity.device_id {
        return Err("This computer is linked to another account or session".into());
    }
    request.operations.validate().map_err(str::to_owned)?;
    if request.name.chars().count() > 200 || request.root.len() > 4096 {
        return Err("The routine name or folder exceeds its size limit".into());
    }
    let requested_root = local_root(Path::new(&request.root)).map_err(str::to_owned)?;
    let approved_folder = crate::local_fs::open(&requested_root)
        .map_err(|_| "Choose an available folder without symbolic links".to_owned())?;
    if request.operations.write && !crate::local_work::modes().contains(&"workspace_write") {
        return Err("This computer cannot sandbox routine writes and commands; choose read only".into());
    }
    let root = request.root;
    let allowed = if request.operations.execute {
        "read, write and sandboxed commands"
    } else if request.operations.write {
        "read and write"
    } else {
        "read only"
    };
    let (answered, answer) = tokio::sync::oneshot::channel();
    let (title, message) = match request.routine_id {
        Some(routine_id) => (
            "Allow this routine to work in this folder?",
            format!(
                "Routine: {}\nRoutine ID: {}\nOrganization ID: {}\nServer: {}\nFolder: {}\nAllowed: {}\n\n\
            This routine may use these operations without this dialog while the app is open. \
            Revoke this permission in Desktop settings to stop future operations.",
                request.name, routine_id, request.organization_id, identity.origin, root, allowed,
            ),
        ),
        None => (
            "Allow your routines to work in this folder?",
            format!(
                "Every routine you set up to act as you in this organization, now or later, may use \
            this folder and the folders inside it.\n\nOrganization ID: {}\nServer: {}\nFolder: {}\nAllowed: {}\n\n\
            They run without this dialog while the app is open, also after you sign in again. \
            Revoke this permission in Desktop settings to stop future operations.",
                request.organization_id, identity.origin, root, allowed,
            ),
        ),
    };
    app.dialog()
        .message(message)
        .title(title)
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Allow routine".into(),
            "Cancel".into(),
        ))
        .show(move |allowed| {
            let _ = answered.send(allowed);
        });
    if !answer.await.unwrap_or(false) {
        return Ok(None);
    }
    if crate::device::identity(&app)? != identity {
        return Err("The device connection changed; review the routine again".into());
    }
    drop(approved_folder);
    let grant = RoutineGrant {
        id: Uuid::new_v4(),
        identity,
        organization_id: request.organization_id,
        routine_id: request.routine_id,
        name: request.name,
        root,
        operations: request.operations,
    };
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    let store = store(&app)?;
    let mut grants = store.load()?;
    // A shared grant may already be referenced by other routines. Only an
    // explicit regrant for one routine replaces that routine's old authority.
    grants.retain(|old| !grant.replaces(old));
    if grants.len() >= MAX_GRANTS {
        return Err("Remove an unused routine permission before adding another".into());
    }
    grants.push(grant.clone());
    store.save(&grants)?;
    Ok(Some(grant))
}

pub fn context(args: &Map<String, Value>) -> Result<WorkContext, String> {
    serde_json::from_value(args.get("work_context").cloned().unwrap_or(Value::Null))
        .map_err(|_| "The server must supply a current local-work context; update API and workers".into())
}

pub fn check(app: &AppHandle, scope: &RoutineScope, root: &str, op: &str) -> Result<PathBuf, String> {
    let identity = crate::device::identity(app)?;
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    let grants = store(app)?.load()?;
    let grant = grants
        .iter()
        .find(|grant| grant.id == scope.grant_id)
        .ok_or("This routine's folder permission was revoked; review it on this computer")?;
    authorize_folder(grant, &identity, scope, root, op)
}

fn authorize_folder(
    grant: &RoutineGrant,
    identity: &DeviceIdentity,
    scope: &RoutineScope,
    root: &str,
    op: &str,
) -> Result<PathBuf, String> {
    let root = grant.authorize(identity, scope, root, op).map_err(str::to_owned)?;
    // Admission must not follow a replaced grant root or one of its ancestors.
    // Effects reopen without following links too; shell startup retains its FD.
    let directory = crate::local_fs::open(&root)
        .map_err(|_| "The routine folder is unavailable or contains symbolic links".to_owned())?;
    drop(directory);
    Ok(root)
}

pub fn preflight(app: &AppHandle, args: &Map<String, Value>) -> Result<Map<String, Value>, String> {
    let WorkContext::Routine(scope) = context(args)? else {
        return Err("A routine context is required".into());
    };
    let root = args
        .get("root")
        .and_then(Value::as_str)
        .ok_or("A routine folder is required")?;
    let expected_mode = if scope.operations.write {
        "workspace_write"
    } else {
        "read_only"
    };
    if args.get("mode").and_then(Value::as_str) != Some(expected_mode)
        || args.get("computer_grant").is_some_and(|value| !value.is_null())
    {
        return Err("The routine's local-work limits changed; review its permission".into());
    }
    check(app, &scope, root, "routine.check")?;
    Ok(Map::from_iter([("allowed".into(), Value::Bool(true))]))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[derive(Default)]
    struct MemoryAuthority(RefCell<Option<String>>);

    impl StoreAuthority for MemoryAuthority {
        fn read(&self) -> Result<Option<String>, String> {
            Ok(self.0.borrow().clone())
        }
        fn write(&self, fingerprint: &str) -> Result<(), String> {
            *self.0.borrow_mut() = Some(fingerprint.to_owned());
            Ok(())
        }
    }

    fn test_store(path: &Path) -> Store<MemoryAuthority> {
        Store {
            path: path.to_owned(),
            authority: MemoryAuthority::default(),
        }
    }

    #[cfg(unix)]
    #[test]
    fn replacing_the_stored_grant_root_cannot_move_its_authority_outside() {
        let base = std::env::temp_dir().join(format!("agenticos-routine-root-{}", Uuid::new_v4()));
        fs::create_dir_all(base.join("approved")).unwrap();
        fs::create_dir_all(base.join("outside")).unwrap();
        let base = base.canonicalize().unwrap();
        let root = base.join("approved");
        let grant = RoutineGrant {
            id: Uuid::new_v4(),
            identity: DeviceIdentity {
                origin: "https://console.example.com".into(),
                user_id: Uuid::new_v4(),
                device_id: Uuid::new_v4(),
            },
            organization_id: Uuid::new_v4(),
            routine_id: None,
            name: "All routines".into(),
            root: root.to_string_lossy().into_owned(),
            operations: Operations {
                read: true,
                write: false,
                execute: false,
            },
        };
        let scope = RoutineScope {
            grant_id: grant.id,
            organization_id: grant.organization_id,
            routine_id: Uuid::new_v4(),
            user_id: grant.identity.user_id,
            device_id: grant.identity.device_id,
            operations: grant.operations,
        };
        let admitted = authorize_folder(&grant, &grant.identity, &scope, &grant.root, "routine.check").unwrap();
        let child = root.join("child");
        fs::create_dir(&child).unwrap();
        assert!(authorize_folder(
            &grant,
            &grant.identity,
            &scope,
            child.to_str().unwrap(),
            "routine.check"
        )
        .is_ok());
        assert!(authorize_folder(
            &grant,
            &grant.identity,
            &scope,
            root.join("missing").to_str().unwrap(),
            "routine.check"
        )
        .is_err());
        fs::write(root.join("file"), "not a directory").unwrap();
        assert!(authorize_folder(
            &grant,
            &grant.identity,
            &scope,
            root.join("file").to_str().unwrap(),
            "routine.check"
        )
        .is_err());
        for (name, target) in [("internal-alias", child), ("escape", base.join("outside"))] {
            let alias = root.join(name);
            std::os::unix::fs::symlink(target, &alias).unwrap();
            assert!(authorize_folder(
                &grant,
                &grant.identity,
                &scope,
                alias.to_str().unwrap(),
                "routine.check"
            )
            .is_err());
        }

        fs::rename(&root, base.join("moved")).unwrap();
        std::os::unix::fs::symlink(base.join("outside"), &root).unwrap();
        assert!(crate::local_fs::open(&admitted).is_err());
        let result = authorize_folder(&grant, &grant.identity, &scope, &grant.root, "routine.check");
        fs::remove_dir_all(base).unwrap();
        assert!(result.is_err(), "a replaced root was admitted as {result:?}");
    }

    #[test]
    fn replacement_and_revocation_survive_reopening_the_store() {
        let directory = std::env::temp_dir().join(format!("agenticos-routine-grants-{}", Uuid::new_v4()));
        let path = directory.join("routine-access.json");
        let store = test_store(&path);
        assert!(store.load().unwrap().is_empty());
        let grant = RoutineGrant {
            id: Uuid::new_v4(),
            identity: DeviceIdentity {
                origin: "https://console.example.com".into(),
                user_id: Uuid::new_v4(),
                device_id: Uuid::new_v4(),
            },
            organization_id: Uuid::new_v4(),
            routine_id: Some(Uuid::new_v4()),
            name: "Report".into(),
            root: "/work/reports".into(),
            operations: Operations {
                read: true,
                write: false,
                execute: false,
            },
        };
        store.save(std::slice::from_ref(&grant)).unwrap();
        assert_eq!(store.load().unwrap(), vec![grant]);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        }
        store.save(&[]).unwrap();
        assert!(store.load().unwrap().is_empty());
        fs::remove_dir_all(directory).unwrap();
    }

    #[test]
    fn a_grant_for_every_routine_is_held_across_sessions_and_one_routine_s_is_not() {
        let identity = DeviceIdentity {
            origin: "https://console.example.com".into(),
            user_id: Uuid::new_v4(),
            device_id: Uuid::new_v4(),
        };
        let mut grant = RoutineGrant {
            id: Uuid::new_v4(),
            identity: identity.clone(),
            organization_id: Uuid::new_v4(),
            routine_id: None,
            name: "All routines".into(),
            root: "/Users/person".into(),
            operations: Operations {
                read: true,
                write: false,
                execute: false,
            },
        };
        let again = DeviceIdentity {
            device_id: Uuid::new_v4(),
            ..identity.clone()
        };
        assert!(owns(&grant, &again));
        assert!(!owns(
            &grant,
            &DeviceIdentity {
                user_id: Uuid::new_v4(),
                ..again.clone()
            }
        ));
        grant.routine_id = Some(Uuid::new_v4());
        assert!(owns(&grant, &identity));
        assert!(!owns(&grant, &again));
    }

    #[test]
    fn relinking_keeps_only_shared_grants_for_the_verified_person_and_never_restores_revocations() {
        let base = std::env::temp_dir().join(format!("agenticos-relink-grants-{}", Uuid::new_v4()));
        let path = base.join("routine-access.json");
        let store = test_store(&path);
        let identity = DeviceIdentity {
            origin: "https://console.example.com".into(),
            user_id: Uuid::new_v4(),
            device_id: Uuid::new_v4(),
        };
        let shared = RoutineGrant {
            id: Uuid::new_v4(),
            identity: identity.clone(),
            organization_id: Uuid::new_v4(),
            routine_id: None,
            name: "All routines".into(),
            root: "/work".into(),
            operations: Operations {
                read: true,
                write: false,
                execute: false,
            },
        };
        let specific = RoutineGrant {
            id: Uuid::new_v4(),
            routine_id: Some(Uuid::new_v4()),
            ..shared.clone()
        };
        store.save(&[shared.clone(), specific]).unwrap();
        retain_shared_at(&store, Some(&identity)).unwrap();
        let again = DeviceIdentity {
            device_id: Uuid::new_v4(),
            ..identity.clone()
        };
        retain_shared_at(&store, Some(&again)).unwrap();
        assert_eq!(store.load().unwrap(), vec![shared.clone()]);
        // The old session can expire and its keychain identity can be forgotten.
        retain_shared_at(&store, None).unwrap();
        retain_shared_at(&store, Some(&again)).unwrap();
        assert_eq!(store.load().unwrap(), vec![shared.clone()]);
        for changed in [
            DeviceIdentity {
                user_id: Uuid::new_v4(),
                ..again.clone()
            },
            DeviceIdentity {
                origin: "https://other.example".into(),
                ..again.clone()
            },
        ] {
            store.save(std::slice::from_ref(&shared)).unwrap();
            retain_shared_at(&store, Some(&changed)).unwrap();
            assert!(store.load().unwrap().is_empty());
        }
        store.save(&[]).unwrap(); // explicit revoke while pairing
        retain_shared_at(&store, Some(&again)).unwrap();
        assert!(store.load().unwrap().is_empty());
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn corruption_does_not_restore_defaults_or_overwrite_existing_permissions() {
        let directory = std::env::temp_dir().join(format!("agenticos-routine-grants-{}", Uuid::new_v4()));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("routine-access.json");
        let store = test_store(&path);
        fs::write(&path, b"not a grant store").unwrap();
        assert!(store.load().is_err());
        assert_eq!(fs::read(&path).unwrap(), b"not a grant store");
        fs::remove_dir_all(directory).unwrap();
    }

    fn a_shared_grant() -> RoutineGrant {
        RoutineGrant {
            id: Uuid::new_v4(),
            identity: DeviceIdentity {
                origin: "https://console.example.com".into(),
                user_id: Uuid::new_v4(),
                device_id: Uuid::new_v4(),
            },
            organization_id: Uuid::new_v4(),
            routine_id: None,
            name: "All routines".into(),
            root: "/home/person".into(),
            operations: Operations {
                read: true,
                write: true,
                execute: true,
            },
        }
    }

    #[test]
    fn filesystem_edits_cannot_forge_native_approval_or_restore_revoked_grants() {
        let base = std::env::temp_dir().join(format!("agenticos-auth-grants-{}", Uuid::new_v4()));
        let path = base.join("routine-access.json");
        let store = test_store(&path);
        let mut grant = a_shared_grant();
        store.save(std::slice::from_ref(&grant)).unwrap();
        let approved = fs::read(&path).unwrap();
        grant.root = "/".into();
        fs::write(&path, serde_json::to_vec(&[grant]).unwrap()).unwrap();
        assert!(store.load().unwrap_err().contains("unverified or changed"));
        // Verification refuses the tampered file before parsing or authorizing it.
        assert!(retain_shared_at(&store, None).is_err());
        fs::write(&path, &approved).unwrap();
        assert_eq!(store.load().unwrap().len(), 1);
        store.save(&[]).unwrap();
        fs::write(&path, &approved).unwrap();
        assert!(
            store.load().is_err(),
            "restoring a revoked file must not restore authority"
        );
        store.save(&[]).unwrap();
        // A restart has only the durable OS authority, never trust-on-first-use.
        let reopened = Store {
            path: path.clone(),
            authority: store.authority,
        };
        assert!(reopened.load().unwrap().is_empty());
        let unverified = test_store(&path);
        assert!(unverified.load().is_err());
        fs::remove_dir_all(base).unwrap();
    }

    struct UnavailableAuthority;
    impl StoreAuthority for UnavailableAuthority {
        fn read(&self) -> Result<Option<String>, String> {
            Err("keychain unavailable".into())
        }
        fn write(&self, _: &str) -> Result<(), String> {
            Err("keychain unavailable".into())
        }
    }

    #[test]
    fn keychain_failures_never_publish_or_admit_permissions() {
        let base = std::env::temp_dir().join(format!("agenticos-keychain-grants-{}", Uuid::new_v4()));
        let path = base.join("routine-access.json");
        let healthy = test_store(&path);
        healthy.save(&[]).unwrap();
        let store = Store {
            path: path.clone(),
            authority: UnavailableAuthority,
        };
        assert!(store.load().is_err());
        assert!(store.save(&[a_shared_grant()]).is_err());
        assert!(healthy.load().unwrap().is_empty());
        assert_eq!(fs::read_dir(&base).unwrap().count(), 1);
        fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn a_partial_filesystem_publish_fails_closed_and_can_be_explicitly_cleared() {
        let base = std::env::temp_dir().join(format!("agenticos-partial-grants-{}", Uuid::new_v4()));
        let path = base.join("routine-access.json");
        fs::create_dir_all(&path).unwrap(); // rename cannot replace a directory
        let store = test_store(&path);
        assert!(store.save(&[a_shared_grant()]).is_err());
        fs::remove_dir(&path).unwrap();
        fs::write(&path, b"[]").unwrap();
        assert!(store.load().is_err());
        store.save(&[]).unwrap();
        assert!(store.load().unwrap().is_empty());
        fs::remove_dir_all(base).unwrap();
    }
}
