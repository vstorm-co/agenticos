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
//! Each instance has a separate Compose project, private configuration, ports,
//! keys and volumes. Setup probes Docker first; its explicit download action is
//! implemented in `docker_install`. Commands come from this module, never a page.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Url};

use crate::local_instances::{self, Instance};
static OPERATIONS: std::sync::Mutex<()> = std::sync::Mutex::new(());
const COMPOSE: &str = include_str!("../../../docker-compose.yml");
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
    let user_cli = std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".docker/bin").join(docker_name()));
    DOCKER_CANDIDATES
        .iter()
        .map(PathBuf::from)
        .chain(user_cli)
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
#[derive(Deserialize, Serialize, Clone)]
pub struct Owner {
    pub email: String,
    pub password: String,
    pub organization: String,
    pub provider: String,
    pub api_key: Option<String>,
    #[serde(default)]
    pub instance_name: Option<String>,
    #[serde(default)]
    pub instance_id: Option<String>,
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
    if owner
        .instance_name
        .as_ref()
        .is_some_and(|name| name.trim().is_empty() || name.chars().count() > 80 || name.chars().any(char::is_control))
    {
        return Err("Name this instance using 1–80 characters.".into());
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

/// Refresh Compose files without replacing an instance's durable keys.
fn write_files(app: &AppHandle, instance: &Instance) -> Result<PathBuf, String> {
    let dir = instance.dir(app)?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    #[cfg(unix)]
    if instance.id != "legacy" {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).map_err(|e| e.to_string())?;
    }
    fs::write(dir.join("docker-compose.yml"), COMPOSE).map_err(|e| e.to_string())?;
    fs::write(
        dir.join("docker-compose.desktop.yml"),
        local_instances::overrides(instance),
    )
    .map_err(|e| e.to_string())?;
    if instance.id != "legacy" {
        local_instances::write_environment(&dir, instance)?;
    }
    Ok(dir)
}
fn compose(docker: &Path, dir: &Path, instance: &Instance) -> Command {
    let mut command = Command::new(docker);
    command
        .current_dir(dir)
        .args(["compose", "--project-name", &instance.project()])
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
pub fn wait_for_console(console: &Url) -> Result<(), String> {
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

/// A published image must support the namespace before credentials are sent or a session opens.
pub fn verify_instance_sessions(instance: &Instance) -> Result<(), String> {
    if instance.id == "legacy" {
        return Ok(());
    }
    #[derive(Deserialize)]
    struct Answer {
        session_cookie_namespace: Option<String>,
    }
    tauri::async_runtime::block_on(async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(10))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?;
        let endpoint = instance.url().join("api/public/endpoints").map_err(|e| e.to_string())?;
        let answer: Answer = client
            .get(endpoint)
            .send()
            .await
            .and_then(reqwest::Response::error_for_status)
            .map_err(|e| format!("Cannot verify this local instance: {e}"))?
            .json()
            .await
            .map_err(|_| "The local frontend did not provide instance session settings.".to_string())?;
        if answer.session_cookie_namespace.as_deref() != Some(instance.id.as_str()) {
            return Err("These AgenticOS images do not support isolated local instances yet. Update to images containing desktop multi-instance support, then retry setup.".into());
        }
        Ok(())
    })
}

/// Set the stack up and create its owner, reporting each step. Blocking: run it
/// off the main thread.
pub fn set_up(app: &AppHandle, owner: &Owner) -> Result<Url, String> {
    validate(owner)?;
    let _operation = OPERATIONS
        .try_lock()
        .map_err(|_| "Another local instance operation is still running.")?;
    let docker = docker().ok_or("Docker is not installed.")?;
    let mut version = Command::new(&docker);
    version.args(["compose", "version"]);
    run(
        version,
        "check Docker Compose; update Docker Desktop if Compose is missing",
    )?;
    let mut instances = local_instances::load(app)?;
    let instance = if let Some(id) = owner.instance_id.as_ref().filter(|id| !id.is_empty()) {
        let instance = instances
            .iter()
            .find(|i| &i.id == id)
            .ok_or("This instance no longer exists.")?;
        if instance.installed {
            return Err("This instance is already installed. Connect to it instead.".into());
        }
        instance.clone()
    } else {
        let name = owner.instance_name.as_deref().unwrap_or(owner.organization.trim());
        let instance = local_instances::allocate(&instances, name)?;
        crate::managed::check(app, &instance.url())?;
        instances.push(instance.clone());
        local_instances::save(app, &instances)?;
        instance
    };
    crate::managed::check(app, &instance.url())?;
    let console = instance.url();

    report(app, Step::Files, None);
    let dir = write_files(app, &instance)?;

    report(app, Step::Download, None);
    let mut pull = compose(&docker, &dir, &instance);
    pull.args(["pull", "--quiet"]);
    run(pull, "download AgenticOS")?;

    report(app, Step::Start, None);
    let mut up = compose(&docker, &dir, &instance);
    up.args(["up", "--detach"]);
    run(up, "start AgenticOS")?;
    wait_for_console(&console)?;
    verify_instance_sessions(&instance)?;

    report(app, Step::Owner, None);
    let mut bootstrap = compose(&docker, &dir, &instance);
    bootstrap.args(["exec", "-T"]);
    // The key travels in the environment, named here and valued only in the
    // Docker CLI's own, so it is never on a command line.
    if let Some(key) = owner.api_key.as_deref().map(str::trim).filter(|key| !key.is_empty()) {
        bootstrap
            .env("BOOTSTRAP_API_KEY", key)
            .args(["-e", "BOOTSTRAP_API_KEY"]);
    }
    // All owner fields travel only through the exec environment, never host argv or files.
    bootstrap.env("AGENTICOS_BOOTSTRAP_OWNER", serde_json::to_string(owner).map_err(|e| e.to_string())?)
        .args(["-e", "AGENTICOS_BOOTSTRAP_OWNER", "app", "python", "-c",
            "import json,os; from app.commands.bootstrap import bootstrap; o=json.loads(os.environ['AGENTICOS_BOOTSTRAP_OWNER']); bootstrap.main(args=['--email',o['email'].strip(),'--password',o['password'],'--org',o['organization'].strip(),'--provider',o['provider']])"]);
    run(bootstrap, "create your organization")?;
    if let Some(saved) = instances.iter_mut().find(|i| i.id == instance.id) {
        saved.installed = true;
    }
    local_instances::save(app, &instances)?;

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
    let instance = local_instances::selected(app)?.ok_or("Choose a managed local instance first.")?;
    control_instance(app, &instance, control)
}

pub fn control_instance(app: &AppHandle, instance: &Instance, control: Control) -> Result<(), String> {
    let _operation = OPERATIONS
        .try_lock()
        .map_err(|_| "Another local instance operation is still running.")?;
    let docker = docker().ok_or("Docker is not installed.")?;
    let dir = write_files(app, instance)?;
    match control {
        Control::Start => {
            let mut up = compose(&docker, &dir, instance);
            up.args(["up", "--detach"]);
            run(up, "start AgenticOS").map(|_| ())
        }
        Control::Stop => {
            let mut stop = compose(&docker, &dir, instance);
            stop.arg("stop");
            run(stop, "stop AgenticOS").map(|_| ())
        }
        Control::Update => {
            let mut pull = compose(&docker, &dir, instance);
            pull.args(["pull", "--quiet"]);
            run(pull, "download the new version")?;
            let mut up = compose(&docker, &dir, instance);
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
    use super::{validate, Owner, COMPOSE};

    fn owner() -> Owner {
        Owner {
            email: "kacper@example.com".into(),
            password: "correct horse".into(),
            organization: "Vstorm".into(),
            provider: "anthropic".into(),
            api_key: Some("sk-secret".into()),
            instance_name: None,
            instance_id: None,
        }
    }

    #[test]
    fn published_frontends_must_advertise_the_matching_session_namespace() {
        use std::io::{Read, Write};
        use std::net::TcpListener;
        for compatible in [true, false] {
            let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
            listener.set_nonblocking(true).unwrap();
            let port = listener.local_addr().unwrap().port();
            let id = uuid::Uuid::new_v4().to_string();
            let body = if compatible {
                format!(r#"{{"session_cookie_namespace":"{id}"}}"#)
            } else {
                "{}".into()
            };
            let server = std::thread::spawn(move || {
                let started = std::time::Instant::now();
                loop {
                    match listener.accept() {
                        Ok((mut stream, _)) => {
                            stream.set_nonblocking(false).unwrap();
                            stream
                                .set_read_timeout(Some(std::time::Duration::from_secs(2)))
                                .unwrap();
                            let mut bytes = [0; 4096];
                            let read = stream.read(&mut bytes).unwrap();
                            let request = String::from_utf8_lossy(&bytes[..read]);
                            assert!(request.starts_with("GET /api/public/endpoints "));
                            assert!(!request.to_ascii_lowercase().contains("authorization:"));
                            write!(stream,"HTTP/1.1 200 OK\r\nContent-Length: {}\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{}",body.len(),body).unwrap();
                            return;
                        }
                        Err(error)
                            if error.kind() == std::io::ErrorKind::WouldBlock
                                && started.elapsed() < std::time::Duration::from_secs(3) =>
                        {
                            std::thread::sleep(std::time::Duration::from_millis(10))
                        }
                        Err(error) => panic!("Metadata probe did not arrive: {error}"),
                    }
                }
            });
            let instance = crate::local_instances::Instance {
                id,
                name: "Test".into(),
                frontend_port: port,
                api_port: 8100,
                installed: false,
            };
            let result = super::verify_instance_sessions(&instance);
            server.join().unwrap();
            assert_eq!(result.is_ok(), compatible);
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
                instance_name: None,
                instance_id: None,
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
        let instance = crate::local_instances::Instance {
            id: "legacy".into(),
            name: "Existing".into(),
            frontend_port: 3000,
            api_port: 8000,
            installed: true,
        };
        let config = crate::local_instances::overrides(&instance);
        assert!(config.contains("127.0.0.1:3000:3000"));
        assert!(config.contains("127.0.0.1:8000:8000"));
        assert_eq!(config.matches("!override").count(), 2);
    }
}
