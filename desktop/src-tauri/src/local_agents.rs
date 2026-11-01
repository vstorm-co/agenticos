//! The coding agents installed on this computer (#2576): whether Claude Code and
//! Codex are there, which version, and whether the person is signed in.
//!
//! Signing in belongs to each agent's own command. The app never reads the
//! files an agent keeps its credentials in and never copies a token: it runs
//! the agent's own `auth status` to learn the state, opens the agent's own
//! sign-in in Terminal, and runs its own sign-out.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::AppHandle;
use tokio::io::AsyncReadExt;

/// The agents the app knows. A closed set: a command names one of these, never
/// a program to run.
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AgentId {
    ClaudeCode,
    Codex,
}

struct Spec {
    id: AgentId,
    name: &'static str,
    program: &'static str,
    status: &'static [&'static str],
    login: &'static [&'static str],
    logout: &'static [&'static str],
}

const SPECS: [Spec; 2] = [
    Spec {
        id: AgentId::ClaudeCode,
        name: "Claude Code",
        program: "claude",
        status: &["auth", "status"],
        login: &["auth", "login"],
        logout: &["auth", "logout"],
    },
    Spec {
        id: AgentId::Codex,
        name: "Codex",
        program: "codex",
        status: &["login", "status"],
        login: &["login"],
        logout: &["logout"],
    },
];

fn spec(id: AgentId) -> &'static Spec {
    SPECS.iter().find(|spec| spec.id == id).expect("every agent has a spec")
}

/// The name shown to the person.
pub(crate) fn name(id: AgentId) -> &'static str {
    spec(id).name
}

/// How long an agent's own command may take to answer a status question.
const PROBE_SECONDS: u64 = 8;

/// One agent's state on this computer.
#[derive(Debug, Serialize, PartialEq, Eq)]
pub struct Agent {
    id: AgentId,
    name: &'static str,
    installed: bool,
    path: Option<String>,
    version: Option<String>,
    /// `None` when the agent is missing or its answer was not understood.
    signed_in: Option<bool>,
}

/// Where a program installed by an agent's own installer, npm or Homebrew lives.
/// A desktop app started from Finder does not inherit the shell's `PATH`, so
/// these are searched after it.
fn fallback_dirs(home: &Path) -> Vec<PathBuf> {
    [
        ".local/bin",
        ".claude/local",
        ".npm-global/bin",
        ".bun/bin",
        ".volta/bin",
        ".cargo/bin",
    ]
    .iter()
    .map(|dir| home.join(dir))
    .chain(["/opt/homebrew/bin", "/usr/local/bin"].map(PathBuf::from))
    .collect()
}

/// The first executable file called `program` in `path_env`'s directories, then
/// in the usual install directories.
fn resolve(program: &str, path_env: Option<&std::ffi::OsStr>, home: Option<&Path>) -> Option<PathBuf> {
    let on_path = path_env.map(|paths| std::env::split_paths(paths).collect::<Vec<_>>());
    on_path
        .into_iter()
        .flatten()
        .chain(home.map(fallback_dirs).into_iter().flatten())
        .map(|dir| dir.join(program))
        .find(|candidate| is_executable(candidate))
}

fn is_executable(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .is_ok_and(|m| m.is_file() && m.permissions().mode() & 0o111 != 0)
    }
    #[cfg(not(unix))]
    {
        path.is_file()
    }
}

pub(crate) fn locate(program: &str) -> Option<PathBuf> {
    let home = std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from);
    resolve(program, std::env::var_os("PATH").as_deref(), home.as_deref())
}

/// Claude Code's `auth status` prints JSON with a `loggedIn` flag.
fn parse_claude_status(output: &str) -> Option<bool> {
    serde_json::from_str::<serde_json::Value>(output)
        .ok()?
        .get("loggedIn")?
        .as_bool()
}

/// Codex's `login status` prints a sentence: "Logged in using ChatGPT" or
/// "Not logged in".
fn parse_codex_status(output: &str) -> Option<bool> {
    let text = output.to_ascii_lowercase();
    if text.contains("not logged in") {
        Some(false)
    } else if text.contains("logged in") {
        Some(true)
    } else {
        None
    }
}

fn parse_status(id: AgentId, output: &str) -> Option<bool> {
    match id {
        AgentId::ClaudeCode => parse_claude_status(output),
        AgentId::Codex => parse_codex_status(output),
    }
}

/// The first line of `--version`, which is all the UI shows.
fn first_line(output: &str) -> Option<String> {
    output
        .lines()
        .map(str::trim)
        .find(|line| !line.is_empty())
        .map(|line| line.chars().take(80).collect())
}

/// Run an agent's own command and return what it printed, stdout then stderr.
async fn run(program: &Path, args: &[&str]) -> Option<String> {
    let mut command = tokio::process::Command::new(program);
    command
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = command.spawn().ok()?;
    let mut stdout = child.stdout.take()?;
    let mut stderr = child.stderr.take()?;
    let collect = async {
        let (mut out, mut err) = (String::new(), String::new());
        let _ = tokio::join!(stdout.read_to_string(&mut out), stderr.read_to_string(&mut err));
        child.wait().await.ok()?;
        out.push_str(&err);
        Some(out)
    };
    tokio::time::timeout(Duration::from_secs(PROBE_SECONDS), collect)
        .await
        .ok()
        .flatten()
}

async fn probe(spec: &Spec) -> Agent {
    let Some(path) = locate(spec.program) else {
        return Agent {
            id: spec.id,
            name: spec.name,
            installed: false,
            path: None,
            version: None,
            signed_in: None,
        };
    };
    let (version, status) = tokio::join!(run(&path, &["--version"]), run(&path, spec.status));
    Agent {
        id: spec.id,
        name: spec.name,
        installed: true,
        path: Some(path.display().to_string()),
        version: version.as_deref().and_then(first_line),
        signed_in: status.as_deref().and_then(|text| parse_status(spec.id, text)),
    }
}

/// Every known agent and its state on this computer.
#[tauri::command]
pub async fn local_agents() -> Vec<Agent> {
    let (claude, codex) = tokio::join!(probe(&SPECS[0]), probe(&SPECS[1]));
    vec![claude, codex]
}

/// A shell script that runs the agent's own sign-in, for Terminal to open: the
/// sign-in is interactive (a browser, sometimes a code), so it needs a terminal.
fn sign_in_script(program: &Path, args: &[&str]) -> String {
    let quote = |text: &str| format!("'{}'", text.replace('\'', "'\\''"));
    let words: Vec<String> = std::iter::once(program.display().to_string())
        .chain(args.iter().map(|arg| (*arg).to_owned()))
        .map(|word| quote(&word))
        .collect();
    format!("#!/bin/sh\nexec {}\n", words.join(" "))
}

/// Open the agent's own sign-in in Terminal. The person finishes it there.
#[tauri::command]
pub async fn local_agent_sign_in(app: AppHandle, id: AgentId) -> Result<(), String> {
    use tauri::Manager;
    use tauri_plugin_opener::OpenerExt;

    let spec = spec(id);
    let program = locate(spec.program).ok_or_else(|| format!("{} is not installed.", spec.name))?;
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| e.to_string())?
        .join("agent-sign-in");
    std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let script = dir.join(format!("{}.command", spec.program));
    std::fs::write(&script, sign_in_script(&program, spec.login)).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    }
    app.opener()
        .open_path(script.display().to_string(), Some("Terminal"))
        .map_err(|e| e.to_string())
}

/// Run the agent's own sign-out, then report its state.
#[tauri::command]
pub async fn local_agent_sign_out(id: AgentId) -> Result<Agent, String> {
    let spec = spec(id);
    let program = locate(spec.program).ok_or_else(|| format!("{} is not installed.", spec.name))?;
    run(&program, spec.logout)
        .await
        .ok_or_else(|| format!("{} did not answer the sign-out.", spec.name))?;
    Ok(probe(spec).await)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_status_reads_the_logged_in_flag() {
        assert_eq!(
            parse_claude_status(r#"{"loggedIn": true, "authMethod": "claude.ai"}"#),
            Some(true)
        );
        assert_eq!(parse_claude_status(r#"{"loggedIn": false}"#), Some(false));
        assert_eq!(parse_claude_status("Error: something else"), None);
        assert_eq!(parse_claude_status(r#"{"authMethod": "x"}"#), None);
    }

    #[test]
    fn codex_status_tells_signed_in_from_signed_out() {
        assert_eq!(parse_codex_status("Logged in using ChatGPT\n"), Some(true));
        assert_eq!(parse_codex_status("Logged in using an API key"), Some(true));
        assert_eq!(parse_codex_status("Not logged in"), Some(false));
        assert_eq!(parse_codex_status("unexpected"), None);
    }

    #[test]
    fn version_is_the_first_nonempty_line_and_bounded() {
        assert_eq!(
            first_line("\n 2.1.316 (Claude Code)\nextra"),
            Some("2.1.316 (Claude Code)".into())
        );
        assert_eq!(first_line("  \n"), None);
        assert_eq!(first_line(&"x".repeat(200)).map(|line| line.len()), Some(80));
    }

    #[cfg(unix)]
    #[test]
    fn resolve_prefers_path_then_the_usual_install_directories() {
        use std::os::unix::fs::PermissionsExt;
        let temp = tempfile_dir();
        let on_path = temp.join("bin");
        let home = temp.join("home");
        std::fs::create_dir_all(&on_path).unwrap();
        std::fs::create_dir_all(home.join(".local/bin")).unwrap();
        let make = |path: &Path, mode: u32| {
            std::fs::write(path, "#!/bin/sh\n").unwrap();
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(mode)).unwrap();
        };
        make(&home.join(".local/bin/claude"), 0o755);
        let path_env = std::env::join_paths([&on_path]).unwrap();
        // Not on PATH: found in ~/.local/bin, where Claude Code's installer puts it.
        assert_eq!(
            resolve("claude", Some(&path_env), Some(&home)),
            Some(home.join(".local/bin/claude"))
        );
        // On PATH as well: PATH wins.
        make(&on_path.join("claude"), 0o755);
        assert_eq!(
            resolve("claude", Some(&path_env), Some(&home)),
            Some(on_path.join("claude"))
        );
        // A file that is not executable is not an install.
        make(&on_path.join("codex"), 0o644);
        assert_eq!(resolve("codex", Some(&path_env), Some(&home)), None);
        std::fs::remove_dir_all(temp).unwrap();
    }

    #[cfg(unix)]
    fn tempfile_dir() -> PathBuf {
        let dir = std::env::temp_dir().join(format!("agenticos-agents-{}", uuid::Uuid::new_v4()));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn sign_in_script_quotes_every_word() {
        let script = sign_in_script(Path::new("/Users/o'brien/bin/claude"), &["auth", "login"]);
        assert_eq!(
            script,
            "#!/bin/sh\nexec '/Users/o'\\''brien/bin/claude' 'auth' 'login'\n"
        );
    }

    #[test]
    fn a_command_names_an_agent_not_a_program() {
        assert!(serde_json::from_str::<AgentId>("\"claude_code\"").is_ok());
        assert!(serde_json::from_str::<AgentId>("\"codex\"").is_ok());
        assert!(serde_json::from_str::<AgentId>("\"/bin/sh\"").is_err());
    }
}
