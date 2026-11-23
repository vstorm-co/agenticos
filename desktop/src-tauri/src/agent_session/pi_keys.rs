//! An isolated Pi configuration, with the selected key only in the child environment.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use serde::Deserialize;
use sha2::{Digest, Sha256};
use tauri::Manager;
use tokio::io::AsyncReadExt;

use crate::external_agents::Provider;

const EXTENSION: &str = include_str!("../../../runtime/pi-key.mjs");
const REQUIRED_VERSION: &str = "1.5.2";

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "lowercase")]
pub(super) enum KeyProvider {
    Inception,
    Deepseek,
    Openrouter,
}

impl KeyProvider {
    pub(super) fn name(self) -> &'static str {
        match self {
            Self::Inception => "inception",
            Self::Deepseek => "deepseek",
            Self::Openrouter => "openrouter",
        }
    }
    fn registration(self) -> Provider {
        match self {
            Self::Inception => Provider::PiInception,
            Self::Deepseek => Provider::PiDeepseek,
            Self::Openrouter => Provider::PiOpenrouter,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SelectedKey {
    provider: KeyProvider,
    api_key: String,
    model_id: String,
}

impl SelectedKey {
    pub(super) fn admits(&self, provider: Provider) -> bool {
        self.provider.registration() == provider
            && self.model_id.starts_with(&format!("{}/", self.provider.name()))
            && self.model_id.len() > self.provider.name().len() + 1
            && self.model_id.len() <= 256
            && self
                .model_id
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || b"._:/@+-".contains(&byte))
            && (8..=16384).contains(&self.api_key.len())
            && self.api_key.bytes().all(|byte| (33..=126).contains(&byte))
    }
    pub(super) fn provider(&self) -> &'static str {
        self.provider.name()
    }
}

pub(super) fn key_template(provider: Provider) -> bool {
    matches!(
        provider,
        Provider::PiInception | Provider::PiDeepseek | Provider::PiOpenrouter
    )
}

pub(super) struct Prepared {
    selected: SelectedKey,
    pub(super) agent_dir: PathBuf,
    session_dir: PathBuf,
    extension: PathBuf,
}

impl Prepared {
    pub(super) async fn new(
        app: &tauri::AppHandle,
        program: &Path,
        scope: Option<&super::ResumeKey>,
        selected: SelectedKey,
    ) -> Result<Self, String> {
        let mut version = tokio::process::Command::new(program);
        version
            .arg("--version")
            .kill_on_drop(true)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(path) = super::path_with(program) {
            version.env("PATH", path);
        }
        let mut child = crate::local_work::spawn_tree(version).map_err(|_| "Could not check Pi's version.")?;
        let stdout = child.0.stdout().take().ok_or("Pi version output is unavailable.")?;
        let checked = tokio::time::timeout(Duration::from_secs(15), async {
            let mut output = Vec::new();
            stdout
                .take(1024)
                .read_to_end(&mut output)
                .await
                .map_err(|_| "Could not read Pi's version.")?;
            let status = child.0.wait().await.map_err(|_| "Could not check Pi's version.")?;
            Ok::<_, &str>((status.success(), output))
        })
        .await
        .map_err(|_| "Pi version check timed out.")??;
        if !checked.0 || String::from_utf8_lossy(&checked.1).trim() != REQUIRED_VERSION {
            return Err("Pi vault-key execution requires CLI 1.5.2. No key was given to the executable.".into());
        }
        let data = app
            .path()
            .app_data_dir()
            .map_err(|_| "Could not open private Pi runtime storage.")?;
        let agent_dir = data.join("pi-key-runtime").join(uuid::Uuid::new_v4().to_string());
        tokio::fs::create_dir_all(&agent_dir)
            .await
            .map_err(|_| "Could not prepare private Pi configuration.")?;
        let session_dir = if let Some(scope) = scope {
            let bytes = serde_json::to_vec(scope).map_err(|_| "Could not scope Pi session storage.")?;
            data.join("pi-key-sessions")
                .join(format!("{:x}", Sha256::digest(bytes)))
        } else {
            agent_dir.join("sessions")
        };
        if tokio::fs::create_dir_all(&session_dir).await.is_err() {
            let _ = tokio::fs::remove_dir_all(&agent_dir).await;
            return Err("Could not prepare Pi session storage.".into());
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            for directory in [&agent_dir, &session_dir] {
                if tokio::fs::set_permissions(directory, std::fs::Permissions::from_mode(0o700))
                    .await
                    .is_err()
                {
                    let _ = tokio::fs::remove_dir_all(&agent_dir).await;
                    return Err("Could not restrict private Pi storage permissions.".into());
                }
            }
        }
        let extension = agent_dir.join("selected-key.mjs");
        if tokio::fs::write(&extension, EXTENSION).await.is_err() {
            let _ = tokio::fs::remove_dir_all(&agent_dir).await;
            return Err("Could not prepare the key-free Pi extension.".into());
        }
        Ok(Self {
            selected,
            agent_dir,
            session_dir,
            extension,
        })
    }

    pub(super) fn apply(&self, command: &mut tokio::process::Command) {
        command
            .args([
                "--provider",
                self.selected.provider(),
                "--model",
                self.selected.model_id.split_once('/').map_or("", |(_, model)| model),
            ])
            .arg("--session-dir")
            .arg(&self.session_dir)
            .arg("--extension")
            .arg(&self.extension)
            .env("PI_CODING_AGENT_DIR", &self.agent_dir)
            .env("AGENTICOS_PI_PROVIDER", self.selected.provider())
            .env("AGENTICOS_PI_KEY", &self.selected.api_key)
            .env_remove("DEEPSEEK_API_KEY")
            .env_remove("OPENROUTER_API_KEY")
            .env_remove("INCEPTION_API_KEY");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn selected_keys_are_environment_only_and_override_other_local_pi_configuration() {
        let selected: SelectedKey =
            serde_json::from_value(serde_json::json!({"provider":"openrouter","api_key":"selected-private-key","model_id":"openrouter/native-model"}))
                .unwrap();
        let prepared = Prepared {
            selected,
            agent_dir: PathBuf::from("/private/isolated"),
            session_dir: PathBuf::from("/private/sessions"),
            extension: PathBuf::from("/private/key-free.mjs"),
        };
        let mut command = tokio::process::Command::new("pi");
        prepared.apply(&mut command);
        let env: std::collections::HashMap<_, _> = command.as_std().get_envs().collect();
        assert_eq!(
            env.get(std::ffi::OsStr::new("AGENTICOS_PI_KEY")).unwrap().unwrap(),
            "selected-private-key"
        );
        assert_eq!(
            env.get(std::ffi::OsStr::new("PI_CODING_AGENT_DIR")).unwrap().unwrap(),
            "/private/isolated"
        );
        assert!(env.get(std::ffi::OsStr::new("OPENROUTER_API_KEY")).unwrap().is_none());
        assert!(!command
            .as_std()
            .get_args()
            .any(|argument| argument.to_string_lossy().contains("selected-private-key")));
        assert!(!EXTENSION.contains("selected-private-key"));
    }

    #[test]
    fn selected_keys_require_the_matching_native_template_and_safe_header_bytes() {
        for (provider, registration) in [
            ("inception", Provider::PiInception),
            ("deepseek", Provider::PiDeepseek),
            ("openrouter", Provider::PiOpenrouter),
        ] {
            let selected: SelectedKey =
                serde_json::from_value(serde_json::json!({"provider":provider,"api_key":"selected-private-key","model_id":format!("{provider}/native-model")}))
                    .unwrap();
            assert!(selected.admits(registration));
            assert!(!selected.admits(Provider::Pi));
        }
        let selected: SelectedKey = serde_json::from_value(
            serde_json::json!({"provider":"deepseek","api_key":"key\nInjected","model_id":"deepseek/native-model"}),
        )
        .unwrap();
        assert!(!selected.admits(Provider::PiDeepseek));
    }
}
