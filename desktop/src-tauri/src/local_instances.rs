//! Public metadata for isolated Compose projects; credentials stay out of this registry.
use serde::{Deserialize, Serialize};
use std::fs;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Manager, Url};

#[derive(Clone, Serialize, Deserialize, Debug)]
pub struct Instance {
    pub id: String,
    pub name: String,
    pub frontend_port: u16,
    pub api_port: u16,
    pub installed: bool,
}
impl Instance {
    pub fn url(&self) -> Url {
        Url::parse(&format!(
            "http://{}:{}/",
            if self.id == "legacy" { "localhost" } else { "127.0.0.1" },
            self.frontend_port
        ))
        .expect("loopback URL")
    }
    pub fn project(&self) -> String {
        if self.id == "legacy" {
            "agenticos-local".into()
        } else {
            format!("agenticos-{}", self.id)
        }
    }
    pub fn dir(&self, app: &AppHandle) -> Result<PathBuf, String> {
        let root = app.path().app_data_dir().map_err(|e| e.to_string())?;
        Ok(if self.id == "legacy" {
            root.join("local-stack")
        } else {
            root.join("local-stacks").join(&self.id)
        })
    }
}
fn path(app: &AppHandle) -> Result<PathBuf, String> {
    Ok(app
        .path()
        .app_config_dir()
        .map_err(|e| e.to_string())?
        .join("local-instances.json"))
}
fn validate(instances: &[Instance]) -> Result<(), String> {
    let mut ports = std::collections::HashSet::new();
    let mut ids = std::collections::HashSet::new();
    for instance in instances {
        if instance.id != "legacy" {
            uuid::Uuid::parse_str(&instance.id).map_err(|_| "Invalid local instance id.")?;
        }
        if !ids.insert(&instance.id)
            || instance.name.trim().is_empty()
            || instance.name.chars().count() > 80
            || instance.name.chars().any(char::is_control)
        {
            return Err("Invalid or duplicate local instance.".into());
        }
        for port in [instance.frontend_port, instance.api_port] {
            if port < 1024 || !ports.insert(port) {
                return Err("Local instances have invalid or overlapping ports.".into());
            }
        }
    }
    Ok(())
}
pub fn load(app: &AppHandle) -> Result<Vec<Instance>, String> {
    let registry = path(app)?;
    let mut instances: Vec<Instance> = match fs::read_to_string(&registry) {
        Ok(raw) => serde_json::from_str(&raw).map_err(|e| format!("Cannot read local instance registry: {e}"))?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(error) => return Err(error.to_string()),
    };
    let legacy = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("local-stack/docker-compose.yml");
    if legacy.exists() && !instances.iter().any(|i| i.id == "legacy") {
        instances.push(Instance {
            id: "legacy".into(),
            name: "AgenticOS (existing installation)".into(),
            frontend_port: 3000,
            api_port: 8000,
            installed: true,
        });
    }
    validate(&instances)?;
    Ok(instances)
}
pub fn save(app: &AppHandle, instances: &[Instance]) -> Result<(), String> {
    validate(instances)?;
    let registry = path(app)?;
    let parent = registry.parent().ok_or("No instance configuration directory.")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let temporary = registry.with_extension("json.tmp");
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(instances).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    fs::rename(temporary, registry).map_err(|e| e.to_string())
}
pub fn find(app: &AppHandle, id: &str) -> Result<Instance, String> {
    load(app)?
        .into_iter()
        .find(|i| i.id == id)
        .ok_or_else(|| "This local instance no longer exists.".into())
}
pub fn selected(app: &AppHandle) -> Result<Option<Instance>, String> {
    let origin = crate::settings::current(app).server_url.map(|url| url.origin());
    Ok(load(app)?.into_iter().find(|i| Some(i.url().origin()) == origin))
}
pub fn allocate(instances: &[Instance], name: &str) -> Result<Instance, String> {
    let reserved = instances
        .iter()
        .flat_map(|i| [i.frontend_port, i.api_port])
        .collect::<std::collections::HashSet<_>>();
    for offset in 0..1000 {
        let frontend_port = 3000 + offset;
        let api_port = 8000 + offset;
        if reserved.contains(&frontend_port) || reserved.contains(&api_port) {
            continue;
        }
        if let (Ok(_frontend), Ok(_api)) = (
            TcpListener::bind(("127.0.0.1", frontend_port)),
            TcpListener::bind(("127.0.0.1", api_port)),
        ) {
            let instance = Instance {
                id: uuid::Uuid::new_v4().to_string(),
                name: name.trim().into(),
                frontend_port,
                api_port,
                installed: false,
            };
            validate(std::slice::from_ref(&instance))?;
            return Ok(instance);
        }
    }
    Err("No free local ports are available. Stop an unused application and retry.".into())
}
/// Generate an override rather than editing the shared product Compose file.
pub fn overrides(instance: &Instance) -> String {
    let namespace = if instance.id == "legacy" {
        String::new()
    } else {
        format!(
            "    environment:\n      SESSION_COOKIE_NAMESPACE: \"{}\"\n",
            instance.id
        )
    };
    format!("services:\n  app:\n    ports: !override\n      - \"127.0.0.1:{}:8000\"\n  frontend:\n    ports: !override\n      - \"127.0.0.1:{}:3000\"\n{}", instance.api_port, instance.frontend_port, namespace)
}
/// Only deployment keys are persisted. The owner's password and provider key are never written here.
pub fn write_environment(dir: &Path, instance: &Instance) -> Result<(), String> {
    use std::io::Write;
    let path = dir.join(".env");
    if path.exists() {
        return Ok(());
    }
    let workspace = dir.join("workspaces");
    fs::create_dir_all(&workspace).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&workspace, fs::Permissions::from_mode(0o777)).map_err(|e| e.to_string())?;
    }
    let secret = || format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple());
    let content = format!("SECRET_KEY={}\nVAULT_MASTER_KEY={}\nPOSTGRES_PASSWORD={}\nSANDBOXD_TOKEN={}\nPUBLIC_SITE_URL=http://127.0.0.1:{}\nPUBLIC_API_URL=http://127.0.0.1:{}\nPUBLIC_WS_URL=ws://127.0.0.1:{}\nFRONTEND_URL=http://127.0.0.1:{}\nCORS_ORIGINS=[\"http://127.0.0.1:{}\"]\nSANDBOX_WORKSPACE_ROOT=\"{}\"\n", secret(), secret(), secret(), secret(), instance.frontend_port, instance.api_port, instance.api_port, instance.frontend_port, instance.frontend_port, workspace.to_string_lossy().replace('\\', "/"));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let temporary = dir.join(format!(".env-{}.pending", uuid::Uuid::new_v4()));
    let mut file = options.open(&temporary).map_err(|e| e.to_string())?;
    if let Err(error) = file.write_all(content.as_bytes()).and_then(|()| file.sync_all()) {
        drop(file);
        let _ = fs::remove_file(&temporary);
        return Err(error.to_string());
    }
    drop(file);
    fs::rename(temporary, path).map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn instance() -> Instance {
        Instance {
            id: uuid::Uuid::new_v4().to_string(),
            name: "Work".into(),
            frontend_port: 3100,
            api_port: 8100,
            installed: true,
        }
    }
    #[test]
    fn existing_installations_keep_their_project_url_and_cookie_names() {
        let existing = Instance {
            id: "legacy".into(),
            name: "Existing".into(),
            frontend_port: 3000,
            api_port: 8000,
            installed: true,
        };
        assert_eq!(existing.project(), "agenticos-local");
        assert_eq!(existing.url().as_str(), "http://localhost:3000/");
        assert!(!overrides(&existing).contains("SESSION_COOKIE_NAMESPACE"));
    }

    #[test]
    fn projects_ports_and_cookie_namespaces_are_distinct() {
        let first = instance();
        let mut second = instance();
        second.frontend_port = 3101;
        second.api_port = 8101;
        assert!(validate(&[first.clone(), second.clone()]).is_ok());
        assert_ne!(first.project(), second.project());
        let config = overrides(&second);
        assert!(config.contains("127.0.0.1:3101:3000"));
        assert!(config.contains("127.0.0.1:8101:8000"));
        assert!(config.contains(&second.id));
        second.api_port = first.api_port;
        assert!(validate(&[first, second]).is_err());
    }
    #[test]
    fn path_traversal_and_privileged_ports_are_rejected() {
        let mut value = instance();
        value.id = "../../outside".into();
        assert!(validate(&[value.clone()]).is_err());
        value.id = uuid::Uuid::new_v4().to_string();
        value.frontend_port = 80;
        assert!(validate(&[value]).is_err());
    }
    #[test]
    fn credentials_survive_configuration_refresh() {
        let dir = std::env::temp_dir().join(format!("agenticos-instance-test-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        let value = instance();
        write_environment(&dir, &value).unwrap();
        let first = fs::read_to_string(dir.join(".env")).unwrap();
        write_environment(&dir, &value).unwrap();
        assert_eq!(first, fs::read_to_string(dir.join(".env")).unwrap());
        assert!(first.contains("PUBLIC_API_URL=http://127.0.0.1:8100"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(dir.join(".env")).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        fs::remove_dir_all(dir).unwrap();
    }
}
