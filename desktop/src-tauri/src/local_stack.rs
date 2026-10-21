//! AgenticOS on this computer: the stack the app sets up and runs itself.
//!
//! The first-run onboarding offers two places for AgenticOS to live - this
//! machine, or an organization's server. "This machine" is the repository's own
//! `docker-compose.yml`, the standalone install from the published images,
//! compiled into the binary and written into the app's data directory with one
//! override beside it: the console and the API answer on loopback only. The
//! file's own ports are published on every interface, which is right for a
//! server and wrong for a laptop on a café's network with a fresh owner
//! password.
//!
//! Docker is the one thing it needs, and it is the person's: the app finds the
//! CLI, asks whether the daemon answers, and says what is missing rather than
//! installing anything. Every command it runs is one of a fixed few, with no part
//! of it taken from a page.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, Url};

/// The compose project, so the stack's containers and volumes are named for it
/// and never collide with a `make dev` checkout's.
const PROJECT: &str = "agenticos-local";
const COMPOSE: &str = include_str!("../../../docker-compose.yml");
/// Loopback only. `!override` replaces the list rather than appending to it,
/// which plain merging would do - and an appended `127.0.0.1:3000:3000` beside
/// the original `3000:3000` fails as a port bound twice.
const OVERRIDE: &str = "services:
  app:
    ports: !override
      - \"127.0.0.1:8000:8000\"
  frontend:
    ports: !override
      - \"127.0.0.1:3000:3000\"
";
pub const CONSOLE: &str = "http://localhost:3000/";
pub const PROGRESS_EVENT: &str = "local:progress";
const DOCKER_DOWNLOAD: &str = "https://www.docker.com/products/docker-desktop/";
/// A first pull of every image on a slow line, and then the migrations.
const READY_DEADLINE: Duration = Duration::from_secs(600);
const READY_POLL: Duration = Duration::from_secs(2);
const PROVIDERS: [&str; 4] = ["anthropic", "openai", "google", "openrouter"];

/// Where Docker's CLI usually lives. An app opened from the Finder does not get
/// the login shell's `PATH`, so `docker` alone is found only from a terminal.
const DOCKER_CANDIDATES: [&str; 4] = [
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    "/Applications/Docker.app/Contents/Resources/bin/docker",
    "/usr/bin/docker",
];

/// The Docker CLI, from the usual places and then the `PATH`.
pub fn docker() -> Option<PathBuf> {
    let on_path = std::env::var_os("PATH")
        .map(|path| {
            std::env::split_paths(&path)
                .map(|dir| dir.join(docker_name()))
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    DOCKER_CANDIDATES
        .iter()
        .map(PathBuf::from)
        .chain(on_path)
        .find(|candidate| candidate.is_file())
}

fn docker_name() -> &'static str {
    if cfg!(windows) {
        "docker.exe"
    } else {
        "docker"
    }
}

/// Where the stack is, as far as onboarding and the tray need to know.
#[derive(Serialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    /// No Docker CLI on this machine.
    NoDocker,
    /// Docker is installed and its daemon does not answer - Docker Desktop is not running.
    DockerStopped,
    /// Something already answers where the console would: a `make dev` stack, or this one.
    Running,
    /// Docker is ready and nothing is running yet.
    Ready,
}

pub fn status(console_answers: bool) -> Status {
    let Some(docker) = docker() else {
        return Status::NoDocker;
    };
    if console_answers {
        return Status::Running;
    }
    let daemon = Command::new(docker)
        .arg("info")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    match daemon {
        Ok(exit) if exit.success() => Status::Ready,
        _ => Status::DockerStopped,
    }
}

/// The owner and organization onboarding creates, and the model they start on.
#[derive(Deserialize, Clone)]
pub struct Owner {
    pub email: String,
    pub password: String,
    pub organization: String,
    pub provider: String,
    pub api_key: Option<String>,
}

impl std::fmt::Debug for Owner {
    // Never the password or the key, in a log or a panic message.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Owner")
            .field("email", &self.email)
            .field("organization", &self.organization)
            .field("provider", &self.provider)
            .finish_non_exhaustive()
    }
}

const MIN_PASSWORD: usize = 8;

/// Check what onboarding sends before any of it reaches a command line.
pub fn validate(owner: &Owner) -> Result<(), String> {
    let email = owner.email.trim();
    let (local, domain) = email.split_once('@').unwrap_or(("", ""));
    if local.is_empty() || !domain.contains('.') || email.chars().any(char::is_whitespace) {
        return Err("Enter an email address to sign in with.".to_owned());
    }
    if owner.password.chars().count() < MIN_PASSWORD {
        return Err(format!("Choose a password of at least {MIN_PASSWORD} characters."));
    }
    let organization = owner.organization.trim();
    if organization.is_empty() || organization.chars().count() > 100 {
        return Err("Name your organization - up to 100 characters.".to_owned());
    }
    if !PROVIDERS.contains(&owner.provider.as_str()) {
        return Err(format!("{} is not a provider AgenticOS can start on.", owner.provider));
    }
    Ok(())
}

/// One step of setting the stack up, as onboarding draws it.
#[derive(Serialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum Step {
    Files,
    Download,
    Start,
    Owner,
    Done,
}

#[derive(Serialize, Clone, Debug)]
pub struct Progress {
    pub step: Step,
    /// The last line a command printed, so a long download is visibly moving.
    pub detail: Option<String>,
}

fn stack_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("No data directory for this account: {e}"))?
        .join("local-stack");
    Ok(dir)
}

/// Write the compose file and the override, replacing older copies: an app
/// update brings the compose file of its own release.
fn write_files(dir: &Path) -> Result<(), String> {
    fs::create_dir_all(dir).map_err(|e| format!("Cannot create {}: {e}", dir.display()))?;
    for (name, body) in [
        ("docker-compose.yml", COMPOSE),
        ("docker-compose.desktop.yml", OVERRIDE),
    ] {
        let path = dir.join(name);
        fs::write(&path, body).map_err(|e| format!("Cannot write {}: {e}", path.display()))?;
    }
    Ok(())
}

/// `docker compose` for this project, in its directory, with its two files.
fn compose(docker: &Path, dir: &Path) -> Command {
    let mut command = Command::new(docker);
    command
        .current_dir(dir)
        .args(["compose", "--project-name", PROJECT])
        .args(["--file", "docker-compose.yml", "--file", "docker-compose.desktop.yml"]);
    command
}

fn run(mut command: Command, what: &str) -> Result<Output, String> {
    let output = command
        .output()
        .map_err(|e| format!("Cannot run Docker to {what}: {e}"))?;
    if output.status.success() {
        return Ok(output);
    }
    let said = String::from_utf8_lossy(&output.stderr);
    let last = said.lines().rev().find(|line| !line.trim().is_empty()).unwrap_or("");
    Err(format!("Docker could not {what}: {last}"))
}

fn report(app: &AppHandle, step: Step, detail: Option<String>) {
    if let Err(e) = app.emit_to(crate::WINDOW, PROGRESS_EVENT, Progress { step, detail }) {
        eprintln!("local stack: {e}");
    }
}

/// Wait until the console answers, or the deadline passes.
fn wait_for_console(console: &Url) -> Result<(), String> {
    let started = Instant::now();
    while started.elapsed() < READY_DEADLINE {
        if crate::reachable(console).is_ok() {
            return Ok(());
        }
        std::thread::sleep(READY_POLL);
    }
    Err(
        "AgenticOS did not start within ten minutes. `docker compose logs` in the app's data folder says why."
            .to_owned(),
    )
}

/// Set the stack up and create its owner, reporting each step. Blocking: run it
/// off the main thread.
pub fn set_up(app: &AppHandle, owner: &Owner) -> Result<Url, String> {
    validate(owner)?;
    let docker = docker().ok_or("Docker is not installed.")?;
    let dir = stack_dir(app)?;
    let console = Url::parse(CONSOLE).expect("a literal URL parses");

    report(app, Step::Files, None);
    write_files(&dir)?;

    report(app, Step::Download, None);
    let mut pull = compose(&docker, &dir);
    pull.args(["pull", "--quiet"]);
    run(pull, "download AgenticOS")?;

    report(app, Step::Start, None);
    let mut up = compose(&docker, &dir);
    up.args(["up", "--detach"]);
    run(up, "start AgenticOS")?;
    wait_for_console(&console)?;

    report(app, Step::Owner, None);
    let mut bootstrap = compose(&docker, &dir);
    bootstrap.args(["exec", "-T"]);
    // The key travels in the environment, named here and valued only in the
    // Docker CLI's own, so it is never on a command line.
    if let Some(key) = owner.api_key.as_deref().map(str::trim).filter(|key| !key.is_empty()) {
        bootstrap
            .env("BOOTSTRAP_API_KEY", key)
            .args(["-e", "BOOTSTRAP_API_KEY"]);
    }
    bootstrap
        .args(["app", "agenticos", "cmd", "bootstrap"])
        .args(["--email", owner.email.trim()])
        .args(["--password", &owner.password])
        .args(["--org", owner.organization.trim()])
        .args(["--provider", &owner.provider]);
    run(bootstrap, "create your organization")?;

    report(app, Step::Done, None);
    Ok(console)
}

/// What the tray asks of a stack the app set up.
#[derive(Clone, Copy, Debug)]
pub enum Control {
    Start,
    Stop,
    Update,
}

/// Start, stop or update the stack. Blocking.
pub fn control(app: &AppHandle, control: Control) -> Result<(), String> {
    let docker = docker().ok_or("Docker is not installed.")?;
    let dir = stack_dir(app)?;
    write_files(&dir)?;
    match control {
        Control::Start => {
            let mut up = compose(&docker, &dir);
            up.args(["up", "--detach"]);
            run(up, "start AgenticOS").map(|_| ())
        }
        Control::Stop => {
            let mut stop = compose(&docker, &dir);
            stop.arg("stop");
            run(stop, "stop AgenticOS").map(|_| ())
        }
        Control::Update => {
            let mut pull = compose(&docker, &dir);
            pull.args(["pull", "--quiet"]);
            run(pull, "download the new version")?;
            let mut up = compose(&docker, &dir);
            up.args(["up", "--detach"]);
            run(up, "restart AgenticOS").map(|_| ())
        }
    }
}

/// The page where Docker Desktop is downloaded, in the person's browser.
pub fn docker_download() -> &'static str {
    DOCKER_DOWNLOAD
}

#[cfg(test)]
mod tests {
    use super::{validate, Owner, COMPOSE, OVERRIDE};

    fn owner() -> Owner {
        Owner {
            email: "kacper@example.com".into(),
            password: "correct horse".into(),
            organization: "Vstorm".into(),
            provider: "anthropic".into(),
            api_key: Some("sk-secret".into()),
        }
    }

    #[test]
    fn a_sound_owner_passes() {
        assert!(validate(&owner()).is_ok());
    }

    #[test]
    fn an_owner_that_cannot_sign_in_is_refused_before_docker_runs() {
        for (email, password, organization, provider) in [
            ("not-an-email", "correct horse", "Vstorm", "anthropic"),
            ("a@b", "correct horse", "Vstorm", "anthropic"),
            ("a b@c.d", "correct horse", "Vstorm", "anthropic"),
            ("a@b.c", "short", "Vstorm", "anthropic"),
            ("a@b.c", "correct horse", "  ", "anthropic"),
            ("a@b.c", "correct horse", "Vstorm", "ollama"),
        ] {
            let candidate = Owner {
                email: email.into(),
                password: password.into(),
                organization: organization.into(),
                provider: provider.into(),
                api_key: None,
            };
            assert!(validate(&candidate).is_err(), "{email} {organization} {provider}");
        }
    }

    #[test]
    fn the_password_and_the_key_never_reach_a_debug_print() {
        let printed = format!("{:?}", owner());
        assert!(!printed.contains("correct horse"));
        assert!(!printed.contains("sk-secret"));
        assert!(printed.contains("kacper@example.com"));
    }

    #[test]
    fn the_compiled_in_stack_is_the_standalone_install_and_answers_on_loopback_only() {
        assert!(COMPOSE.contains("ghcr.io/vstorm-co/agenticos-frontend"));
        assert!(
            COMPOSE.contains("\"3000:3000\""),
            "the override replaces the console's port"
        );
        assert!(
            COMPOSE.contains("\"8000:8000\""),
            "the override replaces the API's port"
        );
        assert!(OVERRIDE.contains("127.0.0.1:3000:3000"));
        assert!(OVERRIDE.contains("127.0.0.1:8000:8000"));
        assert_eq!(OVERRIDE.matches("!override").count(), 2);
    }
}
