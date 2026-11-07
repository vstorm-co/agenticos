//! Native, persistent consent for one routine's bounded folder operations.

use std::fs::{self, File, OpenOptions};
use std::io::{ErrorKind, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use agenticos_shell_core::routine_grants::{DeviceIdentity, Operations, RoutineGrant, RoutineScope, WorkContext};
use serde::Deserialize;
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use uuid::Uuid;

#[derive(Default)]
pub struct Access(Mutex<()>);

const MAX_GRANTS: usize = 256;
const MAX_STORE_BYTES: u64 = 4 * 1024 * 1024;

fn store(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join("routine-access.json"))
        .map_err(|_| "The routine permission store is unavailable".into())
}

fn load(path: &Path) -> Result<Vec<RoutineGrant>, String> {
    let file = match File::open(path) {
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
    let grants: Vec<RoutineGrant> = serde_json::from_slice(&bytes)
        .map_err(|_| "Cannot read routine permissions; no routine access is allowed".to_owned())?;
    if grants.len() > MAX_GRANTS {
        return Err("The routine permission store exceeds its grant limit".into());
    }
    Ok(grants)
}

fn save(path: &Path, grants: &[RoutineGrant]) -> Result<(), String> {
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

pub fn clear(app: &AppHandle) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    save(&store(app)?, &[])
}

pub fn revoke_folder(app: &AppHandle, root: &str) -> Result<(), String> {
    let state = app.state::<Access>();
    let _guard = state
        .0
        .lock()
        .map_err(|_| "Routine permissions are unavailable".to_owned())?;
    let path = store(app)?;
    let mut grants = load(&path)?;
    grants.retain(|grant| grant.root != root);
    save(&path, &grants)
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
    Ok(load(&store(&app)?)?
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
    let path = store(&app)?;
    let mut grants = load(&path)?;
    grants.retain(|grant| grant.id != id || !owns(grant, &identity) || grant.organization_id != organization_id);
    save(&path, &grants)
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
    let root = fs::canonicalize(&request.root).map_err(|_| "That folder is not available".to_owned())?;
    if !root.is_dir() {
        return Err("Choose a folder".into());
    }
    if request.operations.write && !crate::local_work::modes().contains(&"workspace_write") {
        return Err("This computer cannot sandbox routine writes and commands; choose read only".into());
    }
    let root = root.to_string_lossy().into_owned();
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
    let path = store(&app)?;
    let mut grants = load(&path)?;
    // One grant per routine, and one for all of a person's routines - replaced,
    // not stacked, so revoking it in settings revokes it.
    grants.retain(|old| {
        !(owns(old, &grant.identity)
            && old.organization_id == grant.organization_id
            && old.routine_id == grant.routine_id)
    });
    if grants.len() >= MAX_GRANTS {
        return Err("Remove an unused routine permission before adding another".into());
    }
    grants.push(grant.clone());
    save(&path, &grants)?;
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
    let grants = load(&store(app)?)?;
    let grant = grants
        .iter()
        .find(|grant| grant.id == scope.grant_id)
        .ok_or("This routine's folder permission was revoked; review it on this computer")?;
    grant.authorize(&identity, scope, root, op).map_err(str::to_owned)
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

    #[test]
    fn replacement_and_revocation_survive_reopening_the_store() {
        let directory = std::env::temp_dir().join(format!("agenticos-routine-grants-{}", Uuid::new_v4()));
        let path = directory.join("routine-access.json");
        assert!(load(&path).unwrap().is_empty());
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
        save(&path, std::slice::from_ref(&grant)).unwrap();
        assert_eq!(load(&path).unwrap(), vec![grant]);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        }
        save(&path, &[]).unwrap();
        assert!(load(&path).unwrap().is_empty());
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
    fn corruption_does_not_restore_defaults_or_overwrite_existing_permissions() {
        let directory = std::env::temp_dir().join(format!("agenticos-routine-grants-{}", Uuid::new_v4()));
        fs::create_dir_all(&directory).unwrap();
        let path = directory.join("routine-access.json");
        fs::write(&path, b"not a grant store").unwrap();
        assert!(load(&path).is_err());
        assert_eq!(fs::read(&path).unwrap(), b"not a grant store");
        fs::remove_dir_all(directory).unwrap();
    }
}
