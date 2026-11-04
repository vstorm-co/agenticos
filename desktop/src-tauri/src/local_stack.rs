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
use tokio::io::AsyncReadExt;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Url};

use crate::docker_runtime;
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

use crate::docker_runtime::docker;

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
    if docker_runtime::ready(&docker).unwrap_or(false) {
        Status::Ready
    } else {
        Status::DockerStopped
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
    /// A safe progress description; raw registry diagnostics stay out of the UI.
    pub detail: Option<String>,
    pub instance_id: Option<String>,
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
    if !dir.join("docker-compose.yml").exists() {
        fs::write(dir.join("docker-compose.yml"), COMPOSE).map_err(|e| e.to_string())?;
    }
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
pub(crate) fn compose(docker: &Path, dir: &Path, instance: &Instance) -> Result<Command, String> {
    compose_from(docker, dir, instance, "docker-compose.yml")
}

fn compose_from(docker: &Path, dir: &Path, instance: &Instance, manifest: &str) -> Result<Command, String> {
    let mut command = docker_runtime::command(docker)?;
    command
        .arg("--config")
        .arg(docker_runtime::public_config(dir)?)
        .env_remove("DOCKER_AUTH_CONFIG");
    command
        .env("DOCKER_HOST", docker_runtime::local_connection(docker)?)
        .env_remove("DOCKER_CONTEXT");
    command
        .current_dir(dir)
        .args(["compose", "--project-name", &instance.project()])
        .args(["--file", manifest, "--file", "docker-compose.desktop.yml"]);
    Ok(command)
}

#[derive(Clone, Serialize)]
pub struct Failure {
    action: String,
    category: &'static str,
    exit_code: Option<i32>,
}
static LAST_FAILURE: std::sync::Mutex<Option<Failure>> = std::sync::Mutex::new(None);

pub fn diagnostic() -> Option<Failure> {
    LAST_FAILURE.lock().ok().and_then(|value| value.clone())
}

fn command_failure(action: &str, stderr: &str, exit_code: Option<i32>) -> String {
    let text = stderr.to_ascii_lowercase();
    let (category, help) = if text.contains("no space left") || text.contains("not enough space") {
        ("storage", "Free up storage and retry. Your workspace data is kept.")
    } else if text.contains("credential") && (text.contains("not found") || text.contains("not installed")) {
        (
            "credential_helper",
            "The local runtime could not find its sign-in helper. Retry preparing this computer.",
        )
    } else if text.contains("unauthorized") || text.contains("authentication required") {
        (
            "registry_access",
            "The image download was refused. Check runtime sign-in or your organization's network policy.",
        )
    } else if text.contains("certificate") || text.contains("proxyconnect") || text.contains("timeout") {
        (
            "network",
            "Check your connection or your organization's proxy settings, then retry.",
        )
    } else {
        (
            "command",
            "Retry, or use Help → Export Diagnostics to share a report. Your workspace data is kept.",
        )
    };
    if let Ok(mut failure) = LAST_FAILURE.lock() {
        *failure = Some(Failure {
            action: action.to_owned(),
            category,
            exit_code,
        });
    }
    format!("Could not {action}. {help}")
}

fn download_detail(text: &str) -> Option<String> {
    // Registry and helper errors can contain private paths or credentials.
    // Only known progress states cross into the console, never raw process output.
    let status = text.lines().rev().find(|line| !line.trim().is_empty())?;
    if status.contains("Download complete") || status.contains("Pull complete") || status.contains("Pulled") {
        Some("A component has finished downloading.".into())
    } else if status.contains("Downloading") {
        Some("Downloading AgenticOS components…".into())
    } else if status.contains("Extracting") {
        Some("Unpacking AgenticOS components…".into())
    } else if status.contains("Pulling") || status.contains("Waiting") {
        Some("Preparing component downloads…".into())
    } else {
        None
    }
}

pub(crate) async fn collect_output(
    mut reader: impl tokio::io::AsyncRead + Unpin,
    progress: Option<(&AppHandle, Step)>,
) -> Result<Vec<u8>, std::io::Error> {
    let mut kept = Vec::new();
    let mut buffer = [0u8; 4096];
    let mut updated = Instant::now() - Duration::from_secs(1);
    loop {
        let count = reader.read(&mut buffer).await?;
        if count == 0 {
            return Ok(kept);
        }
        kept.extend_from_slice(&buffer[..count]);
        if kept.len() > 32 * 1024 {
            kept.drain(..kept.len() - 32 * 1024);
        }
        if let Some((app, step)) = progress {
            if updated.elapsed() >= Duration::from_millis(250) {
                let text = String::from_utf8_lossy(&kept);
                let detail = download_detail(&text);
                report(app, step, detail);
                updated = Instant::now();
            }
        }
    }
}

async fn run_async(
    command: Command,
    what: &str,
    progress: Option<(&AppHandle, Step)>,
    deadline: Duration,
) -> Result<Output, String> {
    let mut command = tokio::process::Command::from(command);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    let mut child = crate::local_work::spawn_tree(command).map_err(|e| format!("Cannot {what}: {}", e.message))?;
    let stdout = child
        .0
        .stdout()
        .take()
        .ok_or("The runtime did not provide its output.")?;
    let stderr = child
        .0
        .stderr()
        .take()
        .ok_or("The runtime did not provide its diagnostics.")?;
    let finished = async {
        let (stdout, stderr, status) = tokio::join!(
            collect_output(stdout, None),
            collect_output(stderr, progress),
            child.0.wait()
        );
        let output = Output {
            status: status.map_err(|e| e.to_string())?,
            stdout: stdout.map_err(|e| e.to_string())?,
            stderr: stderr.map_err(|e| e.to_string())?,
        };
        if output.status.success() {
            return Ok(output);
        }
        let said = String::from_utf8_lossy(&output.stderr);
        Err(command_failure(what, &said, output.status.code()))
    };
    match tokio::time::timeout(deadline, finished).await {
        Ok(result) => result,
        Err(_) => {
            let _ = child.0.start_kill();
            let _ = child.0.wait().await;
            Err(format!(
                "It took too long to {what}. Check your connection and choose Retry. Your workspace data is kept."
            ))
        }
    }
}

pub(crate) fn run(command: Command, what: &str) -> Result<Output, String> {
    run_with_deadline(command, what, Duration::from_secs(600))
}

pub(crate) fn run_with_deadline(command: Command, what: &str, deadline: Duration) -> Result<Output, String> {
    tauri::async_runtime::block_on(run_async(command, what, None, deadline))
}

fn pull(app: &AppHandle, docker: &Path, dir: &Path, instance: &Instance) -> Result<(), String> {
    let mut command = compose(docker, dir, instance)?;
    command.args(["--progress", "plain", "pull"]);
    tauri::async_runtime::block_on(run_async(
        command,
        "download AgenticOS",
        Some((app, Step::Download)),
        Duration::from_secs(1800),
    ))
    .map(|_| ())
}

fn report(app: &AppHandle, step: Step, detail: Option<String>) {
    if let Err(e) = app.emit_to(
        crate::WINDOW,
        PROGRESS_EVENT,
        Progress {
            step,
            detail,
            instance_id: None,
        },
    ) {
        eprintln!("local stack: {e}");
    }
}

/// A listening frontend is not enough: wait for the API and frontend HTTP endpoints.
pub fn wait_for_instance(instance: &Instance) -> Result<(), String> {
    tauri::async_runtime::block_on(async {
        let client = reqwest::Client::builder()
            .timeout(Duration::from_secs(3))
            .connect_timeout(Duration::from_secs(2))
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|e| e.to_string())?;
        let frontend = instance.url().join("api/public/endpoints").map_err(|e| e.to_string())?;
        let api = Url::parse(&format!("http://127.0.0.1:{}/api/v1/health/ready", instance.api_port))
            .map_err(|e| e.to_string())?;
        let started = Instant::now();
        while started.elapsed() < READY_DEADLINE {
            if endpoints_ready(&client, &api, &frontend).await {
                return Ok(());
            }
            tokio::time::sleep(READY_POLL).await;
        }
        Err("AgenticOS is not ready yet. Choose Retry to continue; your workspace and its keys are kept.".into())
    })
}

async fn endpoints_ready(client: &reqwest::Client, api: &Url, frontend: &Url) -> bool {
    let (api, frontend) = tokio::join!(client.get(api.clone()).send(), client.get(frontend.clone()).send());
    api.is_ok_and(|answer| answer.status().is_success()) && frontend.is_ok_and(|answer| answer.status().is_success())
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
    docker_runtime::ensure_running()?;
    let docker = docker().ok_or("The local runtime is not installed. Prepare this computer first.")?;
    let mut version = docker_runtime::command(&docker)?;
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

    app.emit_to(
        crate::WINDOW,
        PROGRESS_EVENT,
        Progress {
            step: Step::Files,
            detail: None,
            instance_id: Some(instance.id.clone()),
        },
    )
    .map_err(|e| e.to_string())?;
    let dir = write_files(app, &instance)?;

    crate::local_preflight::engine(&docker, &dir)?;
    report(app, Step::Download, None);
    pull(app, &docker, &dir, &instance)?;

    report(app, Step::Start, None);
    let mut up = compose(&docker, &dir, &instance)?;
    up.args(["up", "--detach"]);
    run(up, "start AgenticOS")?;
    wait_for_instance(&instance)?;
    verify_instance_sessions(&instance)?;

    report(app, Step::Owner, None);
    let mut bootstrap = compose(&docker, &dir, &instance)?;
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
    if !matches!(control, Control::Stop) {
        docker_runtime::ensure_running()?;
    }
    let docker = docker().ok_or("The local runtime is not installed. Prepare this computer first.")?;
    let dir = write_files(app, instance)?;
    match control {
        Control::Start => {
            let mut up = compose(&docker, &dir, instance)?;
            up.args(["up", "--detach"]);
            run(up, "start AgenticOS").map(|_| ())
        }
        Control::Stop => {
            let mut stop = compose(&docker, &dir, instance)?;
            stop.arg("stop");
            run(stop, "stop AgenticOS").map(|_| ())
        }
        Control::Update => {
            let target = env!("AGENTICOS_PLATFORM_VERSION");
            let current = crate::local_backup::current_version(&docker, &dir, instance)?;
            crate::local_backup::prevent_downgrade(&current, target)?;
            crate::local_preflight::engine(&docker, &dir)?;
            fs::write(dir.join("docker-compose.update.yml"), COMPOSE).map_err(|e| e.to_string())?;
            let mut download = compose_from(&docker, &dir, instance, "docker-compose.update.yml")?;
            download
                .env("AGENTICOS_VERSION", target)
                .args(["--progress", "plain", "pull"]);
            tauri::async_runtime::block_on(run_async(
                download,
                "download the update",
                Some((app, Step::Download)),
                Duration::from_secs(1800),
            ))?;
            crate::local_preflight::engine(&docker, &dir)?;
            let mut database = compose(&docker, &dir, instance)?;
            database.args(["up", "--detach", "--wait", "db"]);
            run(database, "start the database for its backup")?;
            let mut stop = compose(&docker, &dir, instance)?;
            stop.args(["stop", "app", "worker"]);
            run(stop, "pause AgenticOS before its backup")?;
            let backed_up = crate::local_backup::snapshot(&docker, &dir, instance).and_then(|backup| {
                crate::local_backup::apply_configuration(&dir, &backup, target)?;
                Ok(backup)
            });
            let backup = match backed_up {
                Ok(backup) => backup,
                Err(error) => {
                    let mut restart = compose(&docker, &dir, instance)?;
                    restart.args(["up", "--detach"]);
                    return match run(restart, "restart the existing version") {
                        Ok(_) => Err(error),
                        Err(restart) => Err(format!("{error} {restart}")),
                    };
                }
            };
            let mut up = compose(&docker, &dir, instance)?;
            up.args(["up", "--detach"]);
            run(up, "start the updated AgenticOS")
                .map_err(|error| format!("{error} A backup of the previous database, files and keys is saved in {}. Retry the update; no database downgrade was attempted.", backup.display()))?;
            wait_for_instance(instance)?;
            verify_instance_sessions(instance)
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

    #[tokio::test]
    async fn an_open_frontend_port_does_not_hide_an_unready_api() {
        use std::io::{Read, Write};
        use std::net::TcpListener;
        fn endpoint(status: u16) -> (tauri::Url, std::thread::JoinHandle<()>) {
            let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
            listener.set_nonblocking(true).unwrap();
            let port = listener.local_addr().unwrap().port();
            let server = std::thread::spawn(move || {
                let start = std::time::Instant::now();
                loop {
                    match listener.accept() {
                        Ok((mut stream, _)) => {
                            stream.set_nonblocking(false).unwrap();
                            stream
                                .set_read_timeout(Some(std::time::Duration::from_secs(2)))
                                .unwrap();
                            let mut bytes = [0; 4096];
                            let read = stream.read(&mut bytes).unwrap();
                            assert!(read > 0);
                            write!(
                                stream,
                                "HTTP/1.1 {status} Test\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
                            )
                            .unwrap();
                            return;
                        }
                        Err(error)
                            if error.kind() == std::io::ErrorKind::WouldBlock
                                && start.elapsed() < std::time::Duration::from_secs(3) =>
                        {
                            std::thread::sleep(std::time::Duration::from_millis(10))
                        }
                        Err(error) => panic!("Readiness request did not arrive: {error}"),
                    }
                }
            });
            (tauri::Url::parse(&format!("http://127.0.0.1:{port}/")).unwrap(), server)
        }
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(2))
            .build()
            .unwrap();
        for (api, frontend, ready) in [(200, 200, true), (503, 200, false), (200, 503, false)] {
            let (api, api_server) = endpoint(api);
            let (frontend, frontend_server) = endpoint(frontend);
            assert_eq!(super::endpoints_ready(&client, &api, &frontend).await, ready);
            api_server.join().unwrap();
            frontend_server.join().unwrap();
        }
    }

    #[test]
    fn download_progress_does_not_forward_registry_diagnostics() {
        assert!(super::download_detail("secret-token sk-secret").is_none());
        let detail = super::download_detail("Downloading with secret-token sk-secret").unwrap();
        assert!(!detail.contains("sk-secret"));
        assert!(detail.contains("Downloading"));
    }

    #[test]
    fn command_failures_do_not_expose_raw_credentials_or_paths() {
        for raw in [
            "private-token: sk-secret",
            "credential helper not found /private/home",
            "no space left on device sk-secret",
        ] {
            let shown = super::command_failure("download AgenticOS", raw, Some(1));
            assert!(!shown.contains("sk-secret"));
            assert!(!shown.contains("/private/home"));
        }
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn stalled_commands_are_stopped_and_output_is_bounded() {
        let mut command = std::process::Command::new("/bin/sh");
        command.args(["-c", "sleep 30"]);
        let result = super::run_async(command, "test startup", None, std::time::Duration::from_millis(50)).await;
        assert!(result.unwrap_err().contains("Retry"));
        let mut command = std::process::Command::new("/bin/sh");
        command.args(["-c", "head -c 100000 /dev/zero"]);
        let output = super::run_async(command, "test output", None, std::time::Duration::from_secs(5))
            .await
            .unwrap();
        assert_eq!(output.stdout.len(), 32 * 1024);
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
