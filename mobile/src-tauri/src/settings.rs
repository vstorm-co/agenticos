//! Saved origins contain no credentials. WebKit/Android retain origin storage;
//! switching never copies cookies, local storage or an offline outbox.
use serde::{Deserialize, Serialize};
use tauri::Url;

#[derive(Clone, Serialize, Deserialize)]
pub struct Server {
    pub url: Url,
    pub name: String,
}

#[derive(Serialize, Deserialize)]
pub struct Settings {
    #[serde(default)]
    pub server_url: Option<Url>,
    #[serde(default)]
    pub servers: Vec<Server>,
    #[serde(default = "locked_by_default")]
    pub lock: bool,
}

fn locked_by_default() -> bool {
    true
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            server_url: None,
            servers: Vec::new(),
            lock: true,
        }
    }
}

impl Settings {
    /// Other deployments' addresses stay inside the app's bundled picker.
    pub fn visible_servers(&self, local: bool) -> Vec<Server> {
        self.servers
            .iter()
            .filter(|s| local || self.server_url.as_ref() == Some(&s.url))
            .cloned()
            .collect()
    }

    pub fn migrate(&mut self) {
        if let Some(url) = self.server_url.clone() {
            if !self.servers.iter().any(|s| s.url == url) {
                self.servers.push(Server {
                    name: url.host_str().unwrap_or_default().to_owned(),
                    url,
                });
            }
        }
    }

    pub fn remember(&mut self, url: Url, name: Option<String>) -> Result<(), String> {
        self.migrate();
        // Cookies are scoped to hosts, not ports. A second installation on the
        // same host can overwrite authentication even though IndexedDB is isolated.
        if self
            .servers
            .iter()
            .any(|s| s.url.host_str() == url.host_str() && s.url != url)
        {
            return Err("Use a different hostname for each saved server. Cookies are shared across ports on the same host.".to_owned());
        }
        let name = name.unwrap_or_else(|| {
            self.servers
                .iter()
                .find(|s| s.url == url)
                .map(|s| s.name.clone())
                .unwrap_or_else(|| url.host_str().unwrap_or_default().to_owned())
        });
        let name = name.trim();
        if name.is_empty() || name.chars().count() > 80 {
            return Err("Give this server a name of 1 to 80 characters.".to_owned());
        }
        if let Some(server) = self.servers.iter_mut().find(|s| s.url == url) {
            server.name = name.to_owned();
        } else {
            if self.servers.len() >= 20 {
                return Err(
                    "You can save up to 20 servers. Remove one before adding another.".to_owned(),
                );
            }
            self.servers.push(Server {
                url: url.clone(),
                name: name.to_owned(),
            });
        }
        self.server_url = Some(url);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn migration_keeps_existing_session_and_lock_choice() {
        let mut settings: Settings =
            serde_json::from_str(r#"{"server_url":"https://work.example/","lock":false}"#).unwrap();
        settings.migrate();
        settings.migrate();
        assert_eq!(settings.servers.len(), 1);
        assert!(!settings.lock);
        assert!(Settings::default().lock);
        assert!(serde_json::from_str::<Settings>("{}").unwrap().lock);
    }
    #[test]
    fn a_remote_console_cannot_enumerate_other_connections() {
        let mut settings = Settings::default();
        settings
            .remember(Url::parse("https://work.example/").unwrap(), None)
            .unwrap();
        let home = Url::parse("https://home.example/").unwrap();
        settings.remember(home.clone(), None).unwrap();
        assert_eq!(settings.visible_servers(true).len(), 2);
        let remote = settings.visible_servers(false);
        assert_eq!(remote.len(), 1);
        assert_eq!(remote[0].url, home);
    }

    #[test]
    fn remembering_switches_without_duplicating_and_preserves_other_servers() {
        let mut settings = Settings::default();
        let work = Url::parse("https://work.example/").unwrap();
        settings
            .remember(work.clone(), Some("Work".into()))
            .unwrap();
        settings
            .remember(Url::parse("https://home.example/").unwrap(), None)
            .unwrap();
        settings
            .remember(work.clone(), Some("Office".into()))
            .unwrap();
        assert_eq!(settings.server_url, Some(work));
        assert_eq!(settings.servers.len(), 2);
        assert_eq!(settings.servers[0].name, "Office");
        assert!(settings
            .remember(Url::parse("https://work.example:8443/").unwrap(), None)
            .is_err());
        assert!(settings
            .remember(
                Url::parse("https://other.example/").unwrap(),
                Some(" ".into())
            )
            .is_err());
    }
}
