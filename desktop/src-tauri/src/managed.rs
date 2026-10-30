//! The organization's device management (#2305): the server the app connects
//! to, and whether the person may change it.
//!
//! Read once at start-up, from where each platform's management tools put it:
//! a configuration profile's managed preferences on macOS (for the domain
//! `co.vstorm.agenticos`), and a policy file on Windows
//! (`%ProgramData%\AgenticOS\managed.json`) and Linux
//! (`/etc/agenticos/managed.json`). The keys are the same everywhere:
//! `serverUrl`, a string, and `serverLocked`, a boolean.

use std::path::PathBuf;

use agenticos_shell_core::ManagedPolicy;
use serde::Deserialize;
use tauri::{AppHandle, Manager, Url};

/// The policy in force, managed as app state.
pub struct Managed(pub ManagedPolicy);

#[derive(Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct Raw {
    server_url: Option<String>,
    #[serde(default)]
    server_locked: bool,
}

/// A policy document, as JSON.
fn parse(raw: &str) -> Result<ManagedPolicy, String> {
    let raw: Raw = serde_json::from_str(raw).map_err(|e| format!("Not a policy: {e}"))?;
    ManagedPolicy::new(raw.server_url.as_deref(), raw.server_locked, None, false)
}

/// Where this platform's management puts a policy, most specific first.
fn sources() -> Vec<PathBuf> {
    if cfg!(target_os = "macos") {
        let mut paths = Vec::new();
        if let Ok(user) = std::env::var("USER") {
            paths.push(PathBuf::from(format!(
                "/Library/Managed Preferences/{user}/co.vstorm.agenticos.plist"
            )));
        }
        paths.push(PathBuf::from("/Library/Managed Preferences/co.vstorm.agenticos.plist"));
        paths
    } else if cfg!(target_os = "windows") {
        std::env::var("ProgramData")
            .map(|data| vec![PathBuf::from(data).join("AgenticOS").join("managed.json")])
            .unwrap_or_default()
    } else {
        vec![PathBuf::from("/etc/agenticos/managed.json")]
    }
}

/// A source's contents as JSON: a managed preferences plist through `plutil`.
fn read(path: &std::path::Path) -> Option<String> {
    if !path.exists() {
        return None;
    }
    if path.extension().is_some_and(|ext| ext == "plist") {
        let output = std::process::Command::new("/usr/bin/plutil")
            .args(["-convert", "json", "-o", "-"])
            .arg(path)
            .output()
            .ok()?;
        return output
            .status
            .success()
            .then(|| String::from_utf8_lossy(&output.stdout).into_owned());
    }
    std::fs::read_to_string(path).ok()
}

/// The policy in force: the first source there is. One that cannot be read is
/// said where a developer looks and leaves the app unmanaged - a broken policy
/// must not lock anybody out of the app.
pub fn load() -> ManagedPolicy {
    for path in sources() {
        if let Some(raw) = read(&path) {
            return parse(&raw).unwrap_or_else(|e| {
                eprintln!("{}: {e}", path.display());
                ManagedPolicy::default()
            });
        }
    }
    ManagedPolicy::default()
}

pub fn current(app: &AppHandle) -> ManagedPolicy {
    app.try_state::<Managed>()
        .map(|managed| managed.0.clone())
        .unwrap_or_default()
}

/// Refuse a server the organization does not allow.
pub fn check(app: &AppHandle, server: &Url) -> Result<(), String> {
    if current(app).allows(server) {
        Ok(())
    } else {
        Err("Your organization manages which server this app connects to.".to_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::parse;

    #[test]
    fn a_policy_names_the_server_and_whether_it_is_locked() {
        let policy = parse(r#"{"serverUrl":"agenticos.acme.com","serverLocked":true}"#).unwrap();
        assert_eq!(policy.server.unwrap().as_str(), "https://agenticos.acme.com/");
        assert!(policy.server_locked);
        assert_eq!(parse("{}").unwrap(), Default::default());
    }

    #[test]
    fn a_broken_policy_is_refused_rather_than_half_applied() {
        assert!(parse("not json").is_err());
        assert!(parse(r#"{"serverUrl":"ftp://x"}"#).is_err());
    }
}
