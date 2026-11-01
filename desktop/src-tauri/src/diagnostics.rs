//! A file a person can attach to a bug report (#2576).
//!
//! **Help -> Export Diagnostics...** writes one JSON file, to a place the person
//! picks, and nothing leaves the computer on its own. It says which version this is,
//! what the operating system has allowed, which coding agents are installed and
//! signed in, which server the app points at and what the last crash was. It holds no
//! credential, no token, no path under the person's home folder, no page address
//! beyond the server's own origin and no conversation: what a diagnostic must not
//! contain is decided here, not by whoever reads it.
//!
//! A panic is written to `crash.log` in the app's data folder as it happens, because
//! the person who hits one is not the person who can run a debugger.

use std::io::Write;
use std::path::{Path, PathBuf};

use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Url};
use tauri_plugin_dialog::DialogExt;

const CRASH_FILE: &str = "crash.log";
/// The crash log is trimmed to its last part when it grows past this.
const CRASH_LIMIT: u64 = 64 << 10;
/// What a report carries of the crash log.
const CRASH_TAIL: usize = 16 << 10;

/// `scheme://host:port` and nothing else: the path, the query and any user info
/// of an address can name a person or carry a secret.
fn origin_of(url: &Url) -> String {
    url.origin().ascii_serialization()
}

/// The end of `text`, cut at a line start, within `limit` bytes.
fn tail(text: &str, limit: usize) -> &str {
    if text.len() <= limit {
        return text;
    }
    let mut start = text.len() - limit;
    while !text.is_char_boundary(start) {
        start += 1;
    }
    match text[start..].find('\n') {
        Some(newline) => &text[start + newline + 1..],
        None => &text[start..],
    }
}

/// One panic as a line of the crash log. The location and the message, no backtrace.
fn crash_entry(seconds: u64, version: &str, location: &str, message: &str) -> String {
    format!(
        "[{seconds}] v{version} panic at {location}: {}\n",
        message.replace('\n', " ")
    )
}

fn append_crash(dir: &Path, entry: &str) -> std::io::Result<()> {
    std::fs::create_dir_all(dir)?;
    let path = dir.join(CRASH_FILE);
    if std::fs::metadata(&path).is_ok_and(|meta| meta.len() > CRASH_LIMIT) {
        let kept = std::fs::read_to_string(&path).unwrap_or_default();
        std::fs::write(&path, tail(&kept, (CRASH_LIMIT / 2) as usize))?;
    }
    std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?
        .write_all(entry.as_bytes())
}

/// Write every panic to the crash log, then let the previous hook run as before.
pub fn install_panic_hook(app: &AppHandle) {
    let Ok(dir) = app.path().app_data_dir() else {
        return;
    };
    let version = app.package_info().version.to_string();
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let seconds = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |elapsed| elapsed.as_secs());
        let location = info.location().map_or_else(
            || "an unknown place".to_owned(),
            |at| format!("{}:{}", at.file(), at.line()),
        );
        let message = info
            .payload()
            .downcast_ref::<&str>()
            .map(|text| (*text).to_owned())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "a panic with no message".to_owned());
        let _ = append_crash(&dir, &crash_entry(seconds, &version, &location, &message));
        previous(info);
    }));
}

async fn report(app: &AppHandle) -> Value {
    let settings = crate::settings::current(app);
    let agents: Vec<Value> = crate::local_agents::local_agents()
        .await
        .into_iter()
        .map(|agent| agent.summary())
        .collect();
    let readiness = crate::readiness::desktop_readiness(app.clone())
        .await
        .map_or_else(|error| json!({ "error": error }), |state| json!(state));
    let crash = app
        .path()
        .app_data_dir()
        .ok()
        .and_then(|dir| std::fs::read_to_string(dir.join(CRASH_FILE)).ok())
        .map(|log| tail(&log, CRASH_TAIL).to_owned());
    json!({
        "app": {
            "name": app.package_info().name,
            "version": app.package_info().version.to_string(),
            "tauri": tauri::VERSION,
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
        },
        "server": settings.server_url.as_ref().map(origin_of),
        "permissions": readiness,
        "coding_agents": agents,
        "last_crashes": crash,
        "note": "Holds no credentials, tokens, conversations or home-folder paths.",
    })
}

/// Ask where to save the report, write it, and say so. Cancelling writes nothing.
pub async fn export(app: AppHandle) {
    let body = serde_json::to_string_pretty(&report(&app).await).unwrap_or_default();
    let asked = app.clone();
    let chosen = tauri::async_runtime::spawn_blocking(move || -> Option<PathBuf> {
        asked
            .dialog()
            .file()
            .set_file_name("agenticos-diagnostics.json")
            .blocking_save_file()
            .and_then(|path| path.into_path().ok())
    })
    .await
    .ok()
    .flatten();
    let Some(path) = chosen else {
        return;
    };
    let message = match std::fs::write(&path, body) {
        Ok(()) => format!("Saved to {}. Nothing was sent anywhere.", path.display()),
        Err(error) => format!("Could not save the diagnostics: {error}"),
    };
    app.dialog().message(message).title("Diagnostics").show(|_| {});
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_the_origin_of_a_server_address_is_reported() {
        let url = Url::parse("https://user:secret@agenticos.acme.com:8443/org/acme/chat?token=abc#x").unwrap();
        assert_eq!(origin_of(&url), "https://agenticos.acme.com:8443");
        assert_eq!(
            origin_of(&Url::parse("http://localhost:3000/a").unwrap()),
            "http://localhost:3000"
        );
    }

    #[test]
    fn the_tail_starts_at_a_line_and_respects_characters() {
        assert_eq!(tail("short", 100), "short");
        assert_eq!(tail("one\ntwo\nthree\n", 9), "three\n");
        assert_eq!(tail("a very long line with no newline", 10), "no newline");
        // A cut that would land inside a multi-byte character moves forward past it.
        assert_eq!(tail("zażółć", 5), "łć");
    }

    #[test]
    fn a_crash_is_one_line_with_where_and_what() {
        let entry = crash_entry(1_700_000_000, "1.34.0", "src/lib.rs:10", "boom\nsecond line");
        assert_eq!(entry, "[1700000000] v1.34.0 panic at src/lib.rs:10: boom second line\n");
    }

    #[test]
    fn the_crash_log_appends_and_is_trimmed_when_it_grows() {
        let dir = std::env::temp_dir().join(format!("agenticos-diagnostics-{}", uuid::Uuid::new_v4()));
        append_crash(&dir, "first\n").unwrap();
        append_crash(&dir, "second\n").unwrap();
        assert_eq!(
            std::fs::read_to_string(dir.join(CRASH_FILE)).unwrap(),
            "first\nsecond\n"
        );
        let big = "x\n".repeat(CRASH_LIMIT as usize);
        std::fs::write(dir.join(CRASH_FILE), &big).unwrap();
        append_crash(&dir, "latest\n").unwrap();
        let kept = std::fs::read_to_string(dir.join(CRASH_FILE)).unwrap();
        assert!(kept.len() < CRASH_LIMIT as usize && kept.ends_with("latest\n"));
        std::fs::remove_dir_all(dir).unwrap();
    }
}
