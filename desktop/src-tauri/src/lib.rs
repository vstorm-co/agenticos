//! A window around a deployment's console, and the native parts around it.
//!
//! The console itself stays on the server: this shell holds one setting, the
//! address of that server, and points its webview at it. The first launch, and
//! "Change server…" afterwards, show a local page asking for the address;
//! everything after that is the same Next.js application a browser would load,
//! with the same cookies, the same permissions and the same tenant checks.
//!
//! Around it the shell adds what a browser tab cannot have: a window that looks
//! like the platform's own (an inset title bar, a translucent material when the
//! console wears glass, a native menu), blobby on the desktop, a quick ask panel
//! on a global shortcut, notifications that can be answered, and a badge. Each of
//! those that draws anything draws a page of the console, in a window of the
//! shell's; `console.rs` is what those pages may ask of the shell, and from where.

mod activity;
mod appearance;
mod blobby;
mod computer_access;
mod console;
mod context;
mod device;
mod docker_install;
mod dropped;
mod local_browser;
mod local_fs;
mod local_instances;
mod local_services;
mod local_stack;
mod local_work;
mod managed;
mod native_browser;
mod notify;
mod onboarding_permissions;
mod pinned;
mod quick_ask;
mod readiness;
mod screen;
mod settings;
mod shortcuts;
mod updater;
mod webview_profile;
mod widgets;

#[cfg(target_os = "macos")]
use std::fs;
#[cfg(target_os = "macos")]
use std::io::ErrorKind;
use std::net::{TcpStream, ToSocketAddrs};
use std::sync::{mpsc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use agenticos_shell_core::{
    deep_link_return, external_sign_in_url, is_oauth_start, mint_nonce, parse_server_url, PendingSignIn,
};
use base64::Engine;

use tauri::menu::{ContextMenu, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::webview::PageLoadEvent;
use tauri::window::Color;
use tauri::{AppHandle, Emitter, Manager, Theme, Url, WebviewUrl, WebviewWindow, WindowEvent, Wry};
use tauri_plugin_deep_link::DeepLinkExt;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;

#[cfg(target_os = "macos")]
use tauri::RunEvent;

use appearance::{Appearance, Look, Surface};
use settings::{Deployment, Settings};

pub const WINDOW: &str = "main";
const TRAY: &str = "tray";
const CHANGE_SERVER: &str = "change-server";
const RELOAD: &str = "reload";
const SETTINGS: &str = "settings";
const SCREENSHOT_CHAT: &str = "screenshot-chat";
const QUICK_ASK: &str = "quick-ask";
const NEW_CHAT: &str = "new-chat";
const OPEN_CONSOLE: &str = "open-console";
const BACK: &str = "back";
const FORWARD: &str = "forward";
const DOCUMENTATION: &str = "documentation";
const DOCUMENTATION_URL: &str = "https://vstorm-co.github.io/agenticos/desktop/";
/// Review this server connection and any missing account or macOS setup.
const CONNECTION_SETUP: &str = "desktop/readiness?connection=1";
const LOCAL_START: &str = "local-start";
const LOCAL_STOP: &str = "local-stop";
const LOCAL_UPDATE: &str = "local-update";
const PROBE_TIMEOUT: Duration = Duration::from_secs(1);
const PROBE_DEADLINE: Duration = Duration::from_secs(2);
const PENDING_SCREENSHOT_TTL: Duration = Duration::from_secs(120);
/// Where the traffic lights sit on macOS: inset into the console's own sidebar
/// header, vertically centred on its 56px row, the way Finder and Notes put them.
#[cfg(target_os = "macos")]
const TRAFFIC_LIGHTS: (f64, f64) = (18.0, 22.0);
/// The console's background in each mode, painted behind the page while it loads.
/// A transparent window with nothing painted yet shows the desktop through it.
const LOADING_LIGHT: Color = Color(247, 247, 248, 255);
const LOADING_DARK: Color = Color(30, 31, 33, 255);

/// The destinations under Go, with their shortcut, in the sidebar's own order.
const GO: [(&str, &str, &str, &str); 5] = [
    ("go-dashboard", "Dashboard", "/dashboard", "CmdOrCtrl+1"),
    ("go-chat", "Chat", "/chat", "CmdOrCtrl+2"),
    ("go-agents", "Agents", "/agents", "CmdOrCtrl+3"),
    ("go-runs", "Activity", "/runs", "CmdOrCtrl+4"),
    ("go-knowledge", "Knowledge", "/rag", "CmdOrCtrl+5"),
];

/// A screenshot taken for a chat that is still loading; the console's page-load
/// hook takes it once `/chat` has finished loading.
struct PendingScreenshot(Mutex<Option<Pending>>);

/// The capture, the exact page it is for, and when it was taken.
///
/// Navigation off the server is not restricted, so a page that merely ends in
/// `/chat` is not enough to hand a screenshot to: only the chat page on the
/// configured server's origin gets it, and only within two minutes of the press -
/// long enough to sign in on the way, short enough that a capture nobody attached
/// does not surface on an unrelated visit weeks later.
struct Pending {
    png: Vec<u8>,
    chat: Url,
    taken: Instant,
}

impl Pending {
    fn is_for(&self, loaded: &Url) -> bool {
        loaded.origin() == self.chat.origin() && loaded.path().ends_with("/chat")
    }

    fn expired(&self, now: Instant) -> bool {
        now.duration_since(self.taken) > PENDING_SCREENSHOT_TTL
    }
}

/// Why the console opened on the connect page although a server was stored.
///
/// Read once by that page, which shows it above the form; a blank webview is what
/// an unreachable server looks like otherwise, and it says nothing.
struct StartupNotice(Mutex<Option<String>>);

/// `--server <address>` on the command line: the address to use and remember.
///
/// The way out when the window shows the wrong site and the menu is not found:
/// `agenticos-desktop --server http://localhost:3000` from a terminal.
fn server_argument<I: IntoIterator<Item = String>>(args: I) -> Option<String> {
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        if arg == "--server" {
            return args.next();
        }
        if let Some(value) = arg.strip_prefix("--server=") {
            return Some(value.to_owned());
        }
    }
    None
}

/// Where one of the shell's own pages lives inside the webview.
///
/// Tauri serves the local `frontendDist` from a custom scheme on macOS and Linux
/// and from a loopback name on Windows, where WebView2 has no custom schemes.
fn local_page(name: &str) -> Url {
    let origin = if cfg!(windows) {
        "http://tauri.localhost"
    } else {
        "tauri://localhost"
    };
    Url::parse(&format!("{origin}/{name}")).expect("a literal origin and a file name parse")
}

fn connect_page() -> Url {
    local_page("index.html")
}

/// Whether something is listening where the address points.
///
/// A TCP connect, not an HTTP request: the question is "is the stack up", and the
/// answer has to come back before the window shows anything. WebKit renders a
/// refused connection as a blank white page, which is indistinguishable from a
/// console that has not painted yet.
///
/// Resolution and connect run on a thread of their own under one deadline, because
/// `connect_timeout` bounds the connect and nothing bounds the resolver - a laptop
/// opened offline can sit in DNS for its full timeout, and this runs before the
/// window exists. The thread is left to finish on its own.
fn reachable(server: &Url) -> Result<(), String> {
    let host = server.host_str().ok_or_else(|| format!("{server} names no host."))?;
    let port = server
        .port_or_known_default()
        .ok_or_else(|| format!("{server} names no port."))?;
    let target = (host.to_owned(), port);
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let answered = target
            .to_socket_addrs()
            .map(|addrs| {
                addrs
                    .into_iter()
                    .any(|addr| TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).is_ok())
            })
            .unwrap_or(false);
        let _ = tx.send(answered);
    });
    match rx.recv_timeout(PROBE_DEADLINE) {
        Ok(true) => Ok(()),
        _ => Err(format!(
            "Nothing answers at {server}. Start the stack (`make dev`) or change the address."
        )),
    }
}

/// The console's own first page. Not the server's root, which sends everyone to
/// the sign-in form whether or not they are signed in: the shell keeps its
/// session in its cookies, and opening on the form made a signed-in person sign
/// in again on every launch. Somebody signed out is sent on to the form from here.
fn home(server: &Url) -> Url {
    server.join("dashboard").unwrap_or_else(|_| server.clone())
}

/// The stored server when it answers; otherwise the connect page, with the reason.
fn console_start(server: Option<Url>) -> (WebviewUrl, Option<String>) {
    match server {
        Some(server) => match reachable(&server) {
            Ok(()) => (WebviewUrl::External(home(&server)), None),
            Err(notice) => (WebviewUrl::App("index.html".into()), Some(notice)),
        },
        None => (WebviewUrl::App("index.html".into()), None),
    }
}

/// A failure inside one of the shell's own pages, reported where somebody can read it.
///
/// Neither page has a devtools pane a user would open, and the pet's window has no
/// chrome at all: a script that throws there leaves a transparent window that
/// draws nothing, which kinds like no pet rather than like a bug.
#[tauri::command]
fn page_error(window: WebviewWindow, message: String) {
    eprintln!("{}: {message}", window.label());
}

/// Put a window in front of the person - out of the Dock or taskbar if it was
/// minimised, which a focus request alone does not do.
fn raise(window: &WebviewWindow) -> Result<(), String> {
    window.unminimize().map_err(|e| e.to_string())?;
    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
#[link(name = "CoreGraphics", kind = "framework")]
extern "C" {
    fn CGPreflightScreenCaptureAccess() -> bool;
    fn CGRequestScreenCaptureAccess() -> bool;
}

/// Whether this process may record the screen, asking the system to prompt when it may not.
///
/// Without the permission `screencapture -i` exits 0, writes no file and shows no
/// crosshair - indistinguishable from Escape - so the check has to come first. The
/// system prompts once; after that the request is silent, so the Screen Recording
/// pane is opened as well. Both are attributed to the responsible process: the
/// bundle in production, the terminal the binary was launched from under
/// `make desktop-dev`. A grant takes effect after the app is restarted.
#[cfg(target_os = "macos")]
fn screen_capture_allowed() -> bool {
    // SAFETY: both functions take no arguments and return a BOOL; CoreGraphics is linked above.
    if unsafe { CGPreflightScreenCaptureAccess() } {
        return true;
    }
    unsafe { CGRequestScreenCaptureAccess() };
    if let Err(e) = std::process::Command::new("open").arg(SCREEN_RECORDING_PANE).status() {
        eprintln!("screenshot: could not open the Screen Recording pane: {e}");
    }
    false
}

const SCREEN_RECORDING_REFUSED: &str = "Allow screen recording, then restart me.";
#[cfg(target_os = "macos")]
const SCREEN_RECORDING_PANE: &str = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture";

/// Let the person pick a region, and hand back the PNG - or nothing, if they pressed Escape.
///
/// `screencapture -i` is the same crosshair Cmd+Shift+4 gives, silent, into a file
/// of ours.
#[cfg(target_os = "macos")]
fn capture_screen() -> Result<Option<Vec<u8>>, String> {
    if !screen_capture_allowed() {
        return Err(SCREEN_RECORDING_REFUSED.to_owned());
    }
    let path = std::env::temp_dir().join(format!("agenticos-screenshot-{}.png", std::process::id()));
    let status = std::process::Command::new("screencapture")
        .args(["-i", "-x", "-t", "png"])
        .arg(&path)
        .status()
        .map_err(|e| format!("Cannot run screencapture: {e}"))?;
    match fs::read(&path) {
        Ok(bytes) => {
            if let Err(e) = fs::remove_file(&path) {
                eprintln!("screenshot: could not remove {}: {e}", path.display());
            }
            Ok(Some(bytes))
        }
        Err(e) if e.kind() == ErrorKind::NotFound => {
            if !status.success() {
                eprintln!("screenshot: screencapture exited with {status} and wrote no file");
            }
            Ok(None)
        }
        Err(e) => Err(format!("Cannot read {}: {e}", path.display())),
    }
}

#[cfg(not(target_os = "macos"))]
fn capture_screen() -> Result<Option<Vec<u8>>, String> {
    Err("Screenshots are wired up on macOS only so far.".to_owned())
}

/// The script that attaches a PNG to the console's composer.
///
/// The composer takes files from its hidden `<input type="file">`, so the bytes
/// become a `File`, land in that input through a `DataTransfer`, and a `change`
/// event tells React. The input mounts after the page has loaded, hence the
/// retry, bounded so a page that never grows a composer does not spin forever.
fn attach_script(png: &[u8]) -> String {
    let encoded = base64::engine::general_purpose::STANDARD.encode(png);
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!(
        r#"(() => {{
  const bytes = Uint8Array.from(atob("{encoded}"), (c) => c.charCodeAt(0));
  const file = new File([bytes], "screenshot-{stamp}.png", {{ type: "image/png" }});
  const deadline = Date.now() + 8000;
  const attach = () => {{
    const input = document.querySelector('input[type="file"][accept*="image/png"]');
    if (input && !input.disabled) {{
      const transfer = new DataTransfer();
      transfer.items.add(file);
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", {{ bubbles: true }}));
      return;
    }}
    if (Date.now() < deadline) setTimeout(attach, 200);
  }};
  attach();
}})();"#
    )
}

/// Take a screenshot and put it on a new chat: the capture off the main thread,
/// since it waits for a person, then the console to `/chat`, whose page-load hook
/// attaches what was captured. Nothing is held for that hook until the chat's
/// address is known and answering, and it is dropped again if the console could
/// not be pointed there - a capture that went nowhere must not turn up later.
#[tauri::command]
fn desktop_retry_screenshot(app: AppHandle) {
    screenshot_to_chat(&app);
}

fn screenshot_to_chat(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let png = match capture_screen() {
            Ok(Some(png)) => png,
            Ok(None) => return,
            Err(e) => {
                if e == SCREEN_RECORDING_REFUSED {
                    if let Err(error) = open_in_console_at(&app, "/desktop/readiness?repair=screen_capture") {
                        complain(&app, &error);
                    }
                } else {
                    complain(&app, &e);
                }
                return;
            }
        };
        let handle = app.clone();
        let dispatched = app.run_on_main_thread(move || {
            let chat = match chat_url(&handle) {
                Ok(chat) => chat,
                Err(e) => {
                    complain(&handle, &e);
                    return;
                }
            };
            if let Ok(mut slot) = handle.state::<PendingScreenshot>().0.lock() {
                *slot = Some(Pending {
                    png,
                    chat: chat.clone(),
                    taken: Instant::now(),
                });
            }
            #[cfg(target_os = "macos")]
            if let Err(e) = handle.show() {
                eprintln!("screenshot: {e}");
            }
            if let Err(e) = open_console_at(&handle, chat) {
                if let Ok(mut slot) = handle.state::<PendingScreenshot>().0.lock() {
                    *slot = None;
                }
                complain(&handle, &e);
            }
        });
        if let Err(e) = dispatched {
            eprintln!("screenshot: {e}");
        }
    });
}

/// The console window's title: the product's name on its own pages and the
/// configured server, and the host it is showing anywhere else.
///
/// The window has no address bar, and navigation off the server is allowed so
/// that sign-in and MCP consent can come back to it. A page an MCP server sent
/// the console to could draw a convincing sign-in form; the title bar is the one
/// piece of chrome the page cannot draw, so it names where the person is.
/// (#1532 moves those flows to the system browser, which is the full answer.)
fn window_title(loaded: &Url, server: Option<&Url>) -> String {
    let ours = matches!(loaded.scheme(), "tauri")
        || loaded.host_str().is_some_and(|host| host == "tauri.localhost")
        || server.is_some_and(|server| server.origin() == loaded.origin());
    match loaded.host_str() {
        Some(host) if !ours => format!("{host} — AgenticOS"),
        _ => "AgenticOS".to_owned(),
    }
}

#[tauri::command]
fn server_url(app: AppHandle) -> Result<Option<Url>, String> {
    Ok(settings::current(&app).server_url)
}

#[tauri::command]
fn startup_notice(notice: tauri::State<'_, StartupNotice>) -> Option<String> {
    notice.0.lock().map(|mut slot| slot.take()).unwrap_or(None)
}

#[tauri::command]
async fn connect(app: AppHandle, window: WebviewWindow, url: String) -> Result<(), String> {
    let server = parse_server_url(&url)?;
    let probed = server.clone();
    tauri::async_runtime::spawn_blocking(move || reachable(&probed))
        .await
        .map_err(|e| e.to_string())??;
    arrive(&app, &window, server, Deployment::Server).await
}

/// Point the shell at a console that answers, remember where it lives, and
/// review this connection, including for an existing account.
async fn arrive(app: &AppHandle, window: &WebviewWindow, server: Url, deployment: Deployment) -> Result<(), String> {
    let _transition = device::transition(app).await;
    managed::check(app, &server)?;
    device::clear_authority(app).await?;
    let (settings, ()) = settings::update(app, |settings| {
        settings.server_url = Some(server.clone());
        settings.connection_revision = uuid::Uuid::new_v4().to_string();
        settings.deployment = Some(deployment);
    })?;
    // Granted before the page loads: the welcome asks the shell for its state as it mounts.
    console::grant(app, &server)?;
    let landing = server.join(CONNECTION_SETUP).map_err(|e| e.to_string())?;
    window.navigate(landing).map_err(|e| e.to_string())?;
    retarget_companions(app, &server)?;
    start_companions(app, &server, &settings);
    app.state::<ShellMenu>()
        .reflect_local_instance(local_instances::selected(app)?.is_some())
        .map_err(|e| e.to_string())
}

/// What onboarding needs to draw its first screen.
#[derive(serde::Serialize)]
struct OnboardingState {
    server_url: Option<Url>,
    deployment: Option<Deployment>,
    platform: &'static str,
}

#[tauri::command]
fn onboarding_state(app: AppHandle) -> OnboardingState {
    let settings = settings::current(&app);
    OnboardingState {
        server_url: settings.server_url,
        deployment: settings.deployment,
        platform: appearance::platform(),
    }
}

/// Whether Docker is there and running, and whether AgenticOS already answers here.
#[tauri::command]
async fn local_status() -> Result<local_stack::Status, String> {
    tauri::async_runtime::spawn_blocking(|| {
        let console = Url::parse(local_stack::CONSOLE).expect("a literal URL parses");
        local_stack::status(reachable(&console).is_ok())
    })
    .await
    .map_err(|e| e.to_string())
}

#[derive(serde::Serialize)]
struct LocalInstanceView {
    id: String,
    name: String,
    url: String,
    installed: bool,
    running: bool,
}
#[tauri::command]
async fn local_instances(app: AppHandle) -> Result<Vec<LocalInstanceView>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        local_instances::load(&app).map(|rows| {
            rows.into_iter()
                .map(|row| LocalInstanceView {
                    running: reachable(&row.url()).is_ok(),
                    url: row.url().to_string(),
                    id: row.id,
                    name: row.name,
                    installed: row.installed,
                })
                .collect()
        })
    })
    .await
    .map_err(|e| e.to_string())?
}

/// Set AgenticOS up on this computer and sign the console in to it.
#[tauri::command]
async fn set_up_local(app: AppHandle, window: WebviewWindow, owner: local_stack::Owner) -> Result<(), String> {
    // Before installing anything the organization would then refuse.
    managed::check(&app, &Url::parse(local_stack::CONSOLE).expect("a literal URL parses"))?;
    let handle = app.clone();
    let console = tauri::async_runtime::spawn_blocking(move || local_stack::set_up(&handle, &owner))
        .await
        .map_err(|e| e.to_string())??;
    arrive(&app, &window, console, Deployment::Local).await
}

/// Use the AgenticOS already answering on this computer - a `make dev` stack, or one set up before.
#[tauri::command]
async fn use_local(app: AppHandle, window: WebviewWindow, instance_id: Option<String>) -> Result<(), String> {
    let console = if let Some(id) = instance_id {
        let instance = local_instances::find(&app, &id)?;
        if !instance.installed {
            return Err("Finish setting up this instance first.".into());
        }
        managed::check(&app, &instance.url())?;
        let handle = app.clone();
        let url = instance.url();
        let destination = url.clone();
        tauri::async_runtime::spawn_blocking(move || {
            local_stack::control_instance(&handle, &instance, local_stack::Control::Start)?;
            local_stack::wait_for_console(&url)?;
            local_stack::verify_instance_sessions(&instance)
        })
        .await
        .map_err(|e| e.to_string())??;
        destination
    } else {
        Url::parse(local_stack::CONSOLE).expect("a literal URL parses")
    };
    let probed = console.clone();
    tauri::async_runtime::spawn_blocking(move || reachable(&probed))
        .await
        .map_err(|e| e.to_string())??;
    arrive(&app, &window, console, Deployment::Local).await
}

#[tauri::command]
fn open_docker_download(app: AppHandle) -> Result<(), String> {
    app.opener()
        .open_url(local_stack::docker_download(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// The console's welcome is through; from now on the console opens on itself.
#[tauri::command]
fn finish_onboarding(app: AppHandle) -> Result<(), String> {
    settings::update(&app, |settings| settings.onboarded = true).map(|_| ())
}

/// Start, stop or update the stack the app set up, off the main thread, saying how it went.
fn control_local(app: &AppHandle, control: local_stack::Control) {
    let handle = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let said = match local_stack::control(&handle, control) {
            Ok(()) => match control {
                local_stack::Control::Start => "AgenticOS is starting.".to_owned(),
                local_stack::Control::Stop => "AgenticOS is stopped.".to_owned(),
                local_stack::Control::Update => "AgenticOS is up to date.".to_owned(),
            },
            Err(problem) => problem,
        };
        blobby::say(&handle, &said);
    });
}

/// Bring the console forward, opening it again if it was closed while blobby stayed.
#[tauri::command]
fn show_console(app: AppHandle) -> Result<(), String> {
    bring_console(&app)
}

/// Open the shell's local server picker, which validates the address and managed policy.
#[tauri::command]
fn change_server(app: AppHandle) -> Result<(), String> {
    match app.get_webview_window(WINDOW) {
        Some(console) => console
            .navigate(connect_page())
            .map_err(|e| e.to_string())
            .and_then(|()| raise(&console)),
        None => bring_console(&app),
    }
}

/// Each click is a separate request, even while the console is already on /chat.
fn fresh_chat_path() -> String {
    format!("/chat?new={}", uuid::Uuid::new_v4())
}

/// Put the console on a fresh chat, opening it if it was closed. A plain /chat
/// resumes the open thread; the explicit request uses the console's New Chat action.
#[tauri::command]
fn open_chat(app: AppHandle) -> Result<(), String> {
    open_in_console_at(&app, &fresh_chat_path())
}

fn bring_console(app: &AppHandle) -> Result<(), String> {
    if let Some(console) = app.get_webview_window(WINDOW) {
        return raise(&console);
    }
    let settings = settings::current(app);
    let (start, notice) = console_start(settings.server_url);
    if let Ok(mut slot) = app.state::<StartupNotice>().0.lock() {
        *slot = notice;
    }
    open_window(app, start).map(|_| ()).map_err(|e| e.to_string())
}

/// Show the console on one of its own pages: in place when it is already showing
/// the console, so the page swaps the way a click in the sidebar does, and by
/// loading the address otherwise.
///
/// The page is asked through a function it defines (`__agenticosNavigate`)
/// rather than through an event, so a console from before the desktop bridge -
/// an older server the shell was pointed at - still gets there, by a full load.
/// Told to the console with what to start in the chat: `"call"`.
const START_EVENT: &str = "desktop:start";

/// Bring the console's chat forward and have it start something there - a
/// voice call with the selected agent - as its own button would.
pub fn start_in_chat(app: &AppHandle, what: &str) -> Result<(), String> {
    open_in_console_at(app, "/chat")?;
    app.emit_to(WINDOW, START_EVENT, what).map_err(|e| e.to_string())
}

pub fn open_in_console_at(app: &AppHandle, path: &str) -> Result<(), String> {
    if !notify::is_console_path(path) {
        return Err(format!("{path} is not a page of the console."));
    }
    let server = settings::current(app)
        .server_url
        .ok_or("No server yet - connect the console to one first.")?;
    let url = server.join(path).map_err(|e| e.to_string())?;
    let Some(console) = app.get_webview_window(WINDOW) else {
        reachable(&server)?;
        return open_window(app, WebviewUrl::External(url))
            .map(|_| ())
            .map_err(|e| e.to_string());
    };
    let on_console = console.url().is_ok_and(|shown| shown.origin() == server.origin());
    if on_console {
        let literal = serde_json::to_string(path).map_err(|e| e.to_string())?;
        console
            .eval(format!(
                "window.__agenticosNavigate ? window.__agenticosNavigate({literal}) : location.assign({literal})"
            ))
            .map_err(|e| e.to_string())?;
    } else {
        console.navigate(url).map_err(|e| e.to_string())?;
    }
    raise(&console)
}

/// The address of a fresh chat on the configured server, once it answers.
fn chat_url(app: &AppHandle) -> Result<Url, String> {
    let server = settings::current(app)
        .server_url
        .ok_or("No server yet - connect the console to one first.")?;
    reachable(&server)?;
    server.join("chat").map_err(|e| e.to_string())
}

fn open_console_at(app: &AppHandle, url: Url) -> Result<(), String> {
    match app.get_webview_window(WINDOW) {
        Some(console) => {
            console.navigate(url).map_err(|e| e.to_string())?;
            raise(&console)
        }
        None => open_window(app, WebviewUrl::External(url))
            .map(|_| ())
            .map_err(|e| e.to_string()),
    }
}

/// A screenshot that went nowhere, said on stderr and by blobby.
fn complain(app: &AppHandle, problem: &str) {
    eprintln!("screenshot: {problem}");
    blobby::say(app, problem);
}

/// One of the shell's own pages, served from the app rather than a server.
fn is_local_page(url: &Url) -> bool {
    url.scheme() == "tauri" || url.host_str() == Some("tauri.localhost")
}

/// The remote connection review belongs to setup, independent of the console's saved look.
pub(crate) fn page_surface(url: &Url) -> Surface {
    if is_local_page(url) || url.path().trim_end_matches('/').ends_with("/desktop/readiness") {
        Surface::Setup
    } else {
        Surface::Console
    }
}

/// The window's material and the colour behind its page, for what it shows.
pub(crate) fn dress(window: &WebviewWindow, surface: Surface, appearance: Appearance) -> tauri::Result<()> {
    appearance::apply(window, surface, appearance)?;
    let behind = if surface == Surface::Setup && appearance::VIBRANCY {
        Color(0, 0, 0, 0)
    } else {
        loading_color(appearance, window.theme()?)
    };
    window.set_background_color(Some(behind))
}

/// What the console paints behind itself while it loads, in the window's own mode.
fn loading_color(appearance: Appearance, system: Theme) -> Color {
    if appearance.look == Look::Glass && appearance::VIBRANCY {
        return Color(0, 0, 0, 0);
    }
    let dark = match appearance.mode {
        appearance::Mode::Dark => true,
        appearance::Mode::Light => false,
        appearance::Mode::System => system == Theme::Dark,
    };
    if dark {
        LOADING_DARK
    } else {
        LOADING_LIGHT
    }
}

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    let handle = app.clone();
    let appearance = settings::current(app).appearance;
    let version = app.package_info().version.to_string();
    let mut builder = webview_profile::window(app, WINDOW, url)?
        .title("AgenticOS")
        // The console uploads and moves files through DOM drop targets. Tauri's
        // native handler consumes these drops without forwarding them to the page.
        .disable_drag_drop_handler()
        .initialization_script(appearance::shell_script(&version, WINDOW))
        .inner_size(1280.0, 800.0)
        .min_inner_size(900.0, 600.0)
        .theme(appearance::theme(appearance.mode))
        // Transparent wherever a material can be drawn behind it, so glass can
        // be switched on without rebuilding the window; the loading colour is
        // what keeps the desktop from showing through before the page paints.
        .transparent(appearance::VIBRANCY)
        .background_color(loading_color(appearance, Theme::Light))
        // The one navigation this window refuses. Everything else - including
        // the provider's *return* to the console - loads here as it always did.
        .on_navigation(move |url| {
            let server = settings::current(&handle).server_url;
            if !is_oauth_start(server.as_ref(), url) {
                return true;
            }
            let nonce = mint_nonce();
            if let Ok(mut pending) = handle.state::<PendingSignIn>().0.lock() {
                *pending = Some(nonce.clone());
            }
            let opened = external_sign_in_url(url, &nonce);
            if let Err(e) = handle.opener().open_url(opened.as_str(), None::<&str>) {
                eprintln!("Could not open the sign-in in your browser: {e}");
            }
            false
        });
    #[cfg(target_os = "macos")]
    {
        builder = builder
            .title_bar_style(tauri::TitleBarStyle::Overlay)
            .hidden_title(true)
            .traffic_light_position(tauri::LogicalPosition::new(TRAFFIC_LIGHTS.0, TRAFFIC_LIGHTS.1));
    }
    if let Some(effects) = appearance::effects(Surface::Console, appearance.look) {
        builder = builder.effects(effects);
    }
    let window = builder
        .on_page_load(|window, payload| {
            let settings = settings::current(window.app_handle());
            let server = settings.server_url;
            if let Err(e) = window.set_title(&window_title(payload.url(), server.as_ref())) {
                eprintln!("title: {e}");
            }
            // The shell's own pages - onboarding - sit on the window's material,
            // like a system setup assistant; the console wears its own look.
            if matches!(payload.event(), PageLoadEvent::Started) {
                native_browser::hide_all(window.app_handle());
                let surface = page_surface(payload.url());
                if surface == Surface::Setup {
                    if let Some(blobby) = window.app_handle().get_webview_window(blobby::WINDOW) {
                        if let Err(error) = blobby.hide() {
                            eprintln!("hide blobby during setup: {error}");
                        }
                    }
                }
                if let Err(e) = dress(&window, surface, settings.appearance) {
                    eprintln!("appearance: {e}");
                }
            }
            if !matches!(payload.event(), PageLoadEvent::Finished) {
                return;
            }
            let pending_state = window.app_handle().state::<PendingScreenshot>();
            let Ok(mut slot) = pending_state.0.lock() else {
                return;
            };
            let Some(pending) = slot.as_ref() else {
                return;
            };
            if pending.expired(Instant::now()) {
                *slot = None;
                return;
            }
            if !pending.is_for(payload.url()) {
                return;
            }
            if let Some(pending) = slot.take() {
                if let Err(e) = window.eval(attach_script(&pending.png)) {
                    eprintln!("screenshot: could not attach: {e}");
                }
            }
        })
        .build()?;
    // Now that the window exists its theme is known, and a light system with a
    // dark console - or the other way round - gets the right colour behind it.
    if let Ok(system) = window.theme() {
        window.set_background_color(Some(loading_color(appearance, system)))?;
    }
    let keeper = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            if settings::current(keeper.app_handle()).window.keep_running {
                api.prevent_close();
                if let Err(e) = keeper.hide() {
                    eprintln!("close: {e}");
                }
            } else {
                keeper.app_handle().exit(0);
            }
        }
    });
    Ok(window)
}

/// Reuse the native windows when changing servers. Destroy is queued by Tauri:
/// immediately rebuilding can find a handle whose native window is being torn
/// down, including Quick ask's macOS panel. Navigation replaces each document
/// without that teardown and still drops the previous server's page state.
fn retarget_companions<R: tauri::Runtime>(app: &AppHandle<R>, server: &Url) -> Result<(), String> {
    for (label, path) in [(blobby::WINDOW, blobby::PATH), (quick_ask::WINDOW, quick_ask::PATH)] {
        if let Some(window) = app.get_webview_window(label) {
            let page = server.join(path).map_err(|e| e.to_string())?;
            if label == quick_ask::WINDOW {
                window.hide().map_err(|e| e.to_string())?;
            }
            window.navigate(page).map_err(|e| e.to_string())?;
        }
    }
    // Extra panels belong to the old server and must not retain its documents.
    for (label, window) in app.webview_windows() {
        if label != quick_ask::WINDOW && quick_ask::is_panel(&label) {
            window.destroy().map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

/// Open the windows that live beside the console: blobby, when it is shown, and
/// quick ask, built hidden so the shortcut opens it at once. Both are pages of
/// the server, so they wait until there is one that answers, and the server's
/// origin is granted the commands those pages use before either loads.
fn start_companions(app: &AppHandle, server: &Url, settings: &Settings) {
    if let Err(e) = console::grant(app, server) {
        eprintln!("console: {e}");
        return;
    }
    if let Err(e) = blobby::sync(app, Some(server), &settings.blobby) {
        eprintln!("blobby: {e}");
    }
    if app.get_webview_window(quick_ask::WINDOW).is_none() {
        if let Err(e) = quick_ask::prepare(app, server, settings.appearance) {
            eprintln!("quick ask: {e}");
        }
    }
}

/// The menu items shared by the menu bar, the tray icon and blobby's right-click
/// menu, so a checkmark changed in one is changed in all three.
pub struct ShellMenu {
    blobby: blobby::BlobbyMenu,
    open_console: MenuItem<Wry>,
    new_chat: MenuItem<Wry>,
    quick_ask: MenuItem<Wry>,
    screenshot: MenuItem<Wry>,
    settings: MenuItem<Wry>,
    change_server: MenuItem<Wry>,
    local: [MenuItem<Wry>; 3],
}

impl ShellMenu {
    fn build(app: &AppHandle, settings: &Settings) -> tauri::Result<Self> {
        let local = local_instances::selected(app).is_ok_and(|instance| instance.is_some());
        Ok(Self {
            blobby: blobby::BlobbyMenu::build(app, &settings.blobby)?,
            open_console: MenuItem::with_id(app, OPEN_CONSOLE, "Open AgenticOS", true, None::<&str>)?,
            new_chat: MenuItem::with_id(app, NEW_CHAT, "New Chat", true, Some("CmdOrCtrl+N"))?,
            quick_ask: MenuItem::with_id(app, QUICK_ASK, "Quick Ask", true, None::<&str>)?,
            screenshot: MenuItem::with_id(app, SCREENSHOT_CHAT, "Screenshot to New Chat", true, None::<&str>)?,
            settings: MenuItem::with_id(app, SETTINGS, "Settings…", true, Some("CmdOrCtrl+,"))?,
            // Off where the organization manages the server.
            change_server: MenuItem::with_id(
                app,
                CHANGE_SERVER,
                "Change Server…",
                !managed::current(app).server_locked,
                None::<&str>,
            )?,
            local: [
                MenuItem::with_id(app, LOCAL_START, "Start", local, None::<&str>)?,
                MenuItem::with_id(app, LOCAL_STOP, "Stop", local, None::<&str>)?,
                MenuItem::with_id(app, LOCAL_UPDATE, "Update", local, None::<&str>)?,
            ],
        })
    }

    /// Global shortcuts are registered after the menus exist, and can be changed
    /// or cleared in Settings. Shared items update the menu bar, tray and Blobby.
    fn reflect_shortcuts(&self, app: &AppHandle) -> tauri::Result<()> {
        for binding in shortcuts::views(app, &settings::current(app).shortcuts) {
            let item = match binding.action {
                settings::Action::OpenConsole => &self.open_console,
                settings::Action::QuickAsk => &self.quick_ask,
                settings::Action::ScreenshotChat => &self.screenshot,
                _ => continue,
            };
            item.set_accelerator(binding.menu_accelerator())?;
        }
        Ok(())
    }

    /// The local stack's controls are live only while the app runs one.
    fn reflect_local_instance(&self, available: bool) -> tauri::Result<()> {
        for item in &self.local {
            item.set_enabled(available)?;
        }
        Ok(())
    }

    /// The tray's menu, which is also blobby's: everything the shell does, with no window open.
    fn tray(&self, app: &AppHandle) -> tauri::Result<Menu<Wry>> {
        let separator = || PredefinedMenuItem::separator(app);
        let blobby = self.blobby.submenu(app)?;
        let activity = activity::menu(app)?;
        let agents = settings::current(app)
            .pinned_agents
            .iter()
            .map(|agent| MenuItem::with_id(app, pinned::menu_id(agent), &agent.name, true, None::<&str>))
            .collect::<tauri::Result<Vec<_>>>()?;
        let agent_items: Vec<&dyn IsMenuItem<Wry>> = agents.iter().map(|i| i as &dyn IsMenuItem<Wry>).collect();
        // Absent rather than empty: a submenu with nothing in it is a dead end.
        let chat_with = (!agents.is_empty())
            .then(|| Submenu::with_items(app, "New Chat With", true, &agent_items))
            .transpose()?;
        let quit = PredefinedMenuItem::quit(app, Some("Quit AgenticOS"))?;
        let check_updates = MenuItem::with_id(app, "check-updates", "Check for Updates…", true, None::<&str>)?;
        let [start, stop, update] = &self.local;
        let local = Submenu::with_items(app, "AgenticOS on This Computer", true, &[start, stop, update])?;
        let (first, second, third) = (separator()?, separator()?, separator()?);
        let mut items: Vec<&dyn IsMenuItem<Wry>> = vec![&self.open_console, &self.new_chat];
        if let Some(chat_with) = &chat_with {
            items.push(chat_with);
        }
        items.extend([
            &self.quick_ask as &dyn IsMenuItem<Wry>,
            &self.screenshot,
            &first,
            &blobby,
            &activity,
            &local,
            &second,
            &self.settings,
            &self.change_server,
            &check_updates,
            &third,
            &quit,
        ]);
        Menu::with_items(app, &items)
    }

    /// The macOS menu bar. Windows and Linux get none: a menu bar inside the
    /// console's window is the one thing that would make it look like a
    /// browser, and everything in it is in the tray.
    fn menu_bar(&self, app: &AppHandle) -> tauri::Result<Menu<Wry>> {
        let separator = || PredefinedMenuItem::separator(app);
        let app_menu = Submenu::with_items(
            app,
            "AgenticOS",
            true,
            &[
                &PredefinedMenuItem::about(app, Some("About AgenticOS"), None)?,
                &separator()?,
                &self.settings,
                &MenuItem::with_id(app, "check-updates", "Check for Updates…", true, None::<&str>)?,
                &self.change_server,
                &separator()?,
                &PredefinedMenuItem::services(app, None)?,
                &separator()?,
                &PredefinedMenuItem::hide(app, None)?,
                &PredefinedMenuItem::hide_others(app, None)?,
                &PredefinedMenuItem::show_all(app, None)?,
                &separator()?,
                &PredefinedMenuItem::quit(app, None)?,
            ],
        )?;
        let file = Submenu::with_items(
            app,
            "File",
            true,
            &[
                &self.new_chat,
                &self.quick_ask,
                &self.screenshot,
                &separator()?,
                &PredefinedMenuItem::close_window(app, None)?,
            ],
        )?;
        let edit = Submenu::with_items(
            app,
            "Edit",
            true,
            &[
                &PredefinedMenuItem::undo(app, None)?,
                &PredefinedMenuItem::redo(app, None)?,
                &separator()?,
                &PredefinedMenuItem::cut(app, None)?,
                &PredefinedMenuItem::copy(app, None)?,
                &PredefinedMenuItem::paste(app, None)?,
                &PredefinedMenuItem::select_all(app, None)?,
            ],
        )?;
        let view = Submenu::with_items(
            app,
            "View",
            true,
            &[
                &MenuItem::with_id(app, RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?,
                &separator()?,
                &PredefinedMenuItem::fullscreen(app, None)?,
            ],
        )?;
        let destinations = GO
            .iter()
            .map(|(id, label, _, accelerator)| MenuItem::with_id(app, *id, *label, true, Some(*accelerator)))
            .collect::<tauri::Result<Vec<_>>>()?;
        let back = MenuItem::with_id(app, BACK, "Back", true, Some("CmdOrCtrl+["))?;
        let forward = MenuItem::with_id(app, FORWARD, "Forward", true, Some("CmdOrCtrl+]"))?;
        let go_separator = separator()?;
        let mut go_items: Vec<&dyn IsMenuItem<Wry>> = destinations.iter().map(|i| i as &dyn IsMenuItem<Wry>).collect();
        go_items.extend([&go_separator as &dyn IsMenuItem<Wry>, &back, &forward]);
        let go = Submenu::with_items(app, "Go", true, &go_items)?;
        let window = Submenu::with_items(
            app,
            "Window",
            true,
            &[
                &PredefinedMenuItem::minimize(app, None)?,
                &PredefinedMenuItem::maximize(app, Some("Zoom"))?,
                &separator()?,
                &self.open_console,
            ],
        )?;
        let help = Submenu::with_items(
            app,
            "Help",
            true,
            &[&MenuItem::with_id(
                app,
                DOCUMENTATION,
                "AgenticOS Documentation",
                true,
                None::<&str>,
            )?],
        )?;
        Menu::with_items(
            app,
            &[
                &app_menu,
                &file,
                &edit,
                &view,
                &go,
                &self.blobby.submenu(app)?,
                &activity::menu(app)?,
                &window,
                &help,
            ],
        )
    }
}

/// The tray icon's menu, under blobby's right mouse button.
pub fn popup_tray_menu(app: &AppHandle, window: &WebviewWindow) -> Result<(), String> {
    let menu = app.state::<ShellMenu>().tray(app).map_err(|e| e.to_string())?;
    menu.popup(window.as_ref().window()).map_err(|e| e.to_string())
}

/// The pinned agents changed: the tray's menu again, and the Dock's next one.
pub fn reflect_pinned(app: &AppHandle, pinned: &[pinned::PinnedAgent]) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    pinned::dock::set(pinned);
    #[cfg(not(target_os = "macos"))]
    let _ = pinned;
    let Some(tray) = app.tray_by_id(TRAY) else {
        return Ok(());
    };
    let menu = app.state::<ShellMenu>().tray(app).map_err(|e| e.to_string())?;
    tray.set_menu(Some(menu)).map_err(|e| e.to_string())
}

/// Blobby's settings changed: the checkmarks, then the window.
pub fn reflect_blobby(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    app.state::<ShellMenu>()
        .blobby
        .reflect(&settings.blobby)
        .map_err(|e| e.to_string())?;
    blobby::sync(app, settings.server_url.as_ref(), &settings.blobby)
}

/// The count of what is waiting, beside the tray icon - the menu bar's title on
/// macOS, the tooltip elsewhere, where a tray icon has no text of its own.
pub fn tray_badge(app: &AppHandle, count: Option<u32>) -> Result<(), String> {
    let Some(tray) = app.tray_by_id(TRAY) else {
        return Ok(());
    };
    let label = count.map(|n| n.to_string());
    if cfg!(target_os = "macos") {
        tray.set_title(label.as_deref()).map_err(|e| e.to_string())
    } else {
        let tooltip = label.map_or_else(|| "AgenticOS".to_owned(), |n| format!("AgenticOS ({n})"));
        tray.set_tooltip(Some(tooltip)).map_err(|e| e.to_string())
    }
}

/// Whether an agent is working on this computer right now, in the tray's tooltip.
pub fn tray_working(app: &AppHandle, working: bool) {
    let Some(tray) = app.tray_by_id(TRAY) else {
        return;
    };
    let tooltip = if working {
        "AgenticOS - an agent is working on this computer"
    } else {
        "AgenticOS"
    };
    if let Err(e) = tray.set_tooltip(Some(tooltip)) {
        eprintln!("tray tooltip: {e}");
    }
}

fn update_blobby(app: &AppHandle, change: impl FnOnce(&mut blobby::BlobbySettings)) -> Result<(), String> {
    let (settings, ()) = settings::update(app, |settings| change(&mut settings.blobby))?;
    reflect_blobby(app, &settings)
}

fn install_menu(app: &AppHandle, settings: &Settings) -> tauri::Result<TrayIcon> {
    let shell_menu = ShellMenu::build(app, settings)?;
    if cfg!(target_os = "macos") {
        app.set_menu(shell_menu.menu_bar(app)?)?;
    }
    let mut tray = TrayIconBuilder::with_id(TRAY)
        .menu(&shell_menu.tray(app)?)
        .show_menu_on_left_click(true)
        .tooltip("AgenticOS");
    match tauri::image::Image::from_bytes(include_bytes!("../icons/tray-template.png")) {
        Ok(icon) => tray = tray.icon(icon).icon_as_template(true),
        Err(e) => {
            eprintln!("tray icon: {e}");
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
        }
    }
    let tray = tray.build(app)?;
    app.manage(shell_menu);

    app.on_menu_event(|app, event| {
        let id = event.id().as_ref();
        if id.starts_with("activity:") {
            if let Err(error) = activity::handle(app, id) {
                complain(app, &error);
            }
            return;
        }
        let outcome = match id {
            "check-updates" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(error) = updater::check(app.clone()).await {
                        use tauri_plugin_dialog::DialogExt;
                        app.dialog().message(error).title("Update failed").show(|_| {});
                    }
                });
                Ok(())
            }
            NEW_CHAT => open_chat(app.clone()),
            OPEN_CONSOLE => bring_console(app),
            SETTINGS => open_in_console_at(app, "/settings/profile"),
            blobby::CUSTOMIZE_MENU_ID => open_in_console_at(app, "/settings/desktop/blobby"),
            QUICK_ASK => {
                let settings = settings::current(app);
                quick_ask::toggle(app, settings.server_url.as_ref(), settings.appearance)
            }
            SCREENSHOT_CHAT => {
                screenshot_to_chat(app);
                Ok(())
            }
            DOCUMENTATION => app
                .opener()
                .open_url(DOCUMENTATION_URL, None::<&str>)
                .map_err(|e| e.to_string()),
            blobby::SHOW_MENU_ID => update_blobby(app, |blobby| blobby.enabled = !blobby.enabled),
            LOCAL_START | LOCAL_STOP | LOCAL_UPDATE => {
                let control = match id {
                    LOCAL_START => local_stack::Control::Start,
                    LOCAL_STOP => local_stack::Control::Stop,
                    _ => local_stack::Control::Update,
                };
                control_local(app, control);
                Ok(())
            }
            CHANGE_SERVER => change_server(app.clone()),
            RELOAD | BACK | FORWARD => match native_browser::handle_menu(app, id) {
                Ok(true) => Ok(()),
                Err(error) => Err(error),
                Ok(false) => match app.get_webview_window(WINDOW) {
                    Some(console) => {
                        let script = match id {
                            BACK => "history.back()",
                            FORWARD => "history.forward()",
                            _ => "location.reload()",
                        };
                        console.eval(script).map_err(|e| e.to_string())
                    }
                    None => bring_console(app),
                },
            },
            other => {
                if let Some((_, _, path, _)) = GO.iter().find(|(go, ..)| *go == other) {
                    open_in_console_at(app, path)
                } else if let Some(cast) = blobby::cast_from_menu_id(other) {
                    update_blobby(app, |blobby| {
                        blobby.character = blobby::Character::Cast { id: cast };
                        blobby.enabled = true;
                    })
                } else if let Some(size) = blobby::size_from_menu_id(other) {
                    update_blobby(app, |blobby| blobby.size = size)
                } else if let Some(agent) = pinned::from_menu_id(other) {
                    open_in_console_at(app, &pinned::chat_path(agent))
                } else {
                    Ok(())
                }
            }
        };
        if let Err(e) = outcome {
            eprintln!("menu action {id} failed: {e}");
        }
    });
    Ok(tray)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // First, and it has to be: on Windows and Linux opening a registered
        // scheme *starts the executable again*, and a desktop sign-in always
        // begins with an instance already running. Without this the callback
        // would build a second console, tray icon and blobby, consume the code
        // there, and leave the original window signed out - with two processes
        // competing for one global shortcut. The second instance hands its
        // argv over and exits.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Err(e) = bring_console(app) {
                eprintln!("{e}");
            }
        }))
        .manage(local_browser::Browsers::default())
        .manage(native_browser::NativeBrowsers::default())
        .plugin({
            let builder = tauri_plugin_updater::Builder::new();
            match option_env!("AGENTICOS_UPDATER_PUBLIC_KEY") {
                Some(key) if !key.is_empty() => builder.pubkey(key).build(),
                _ => builder.build(),
            }
        })
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        // The console's size and place, and only the console's: blobby keeps
        // its own position in the settings, and quick ask is placed where the
        // cursor is every time it opens.
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_denylist(&[blobby::WINDOW, quick_ask::WINDOW])
                .with_state_flags(
                    tauri_plugin_window_state::StateFlags::all() & !tauri_plugin_window_state::StateFlags::VISIBLE,
                )
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            native_browser::native_browser_view,
            native_browser::native_browser_input,
            change_server,
            server_url,
            startup_notice,
            connect,
            page_error,
            show_console,
            open_chat,
            console::desktop_state,
            console::set_appearance,
            console::set_blobby,
            console::save_blobby_position,
            console::resize_blobby,
            console::blobby_menu,
            console::set_window_preferences,
            desktop_retry_screenshot,
            readiness::desktop_readiness,
            readiness::desktop_request_permission,
            readiness::desktop_is_focused,
            activity::desktop_activity,
            console::notify,
            console::set_badge,
            console::open_in_console,
            console::pin_agent,
            console::unpin_agent,
            onboarding_state,
            onboarding_permissions::onboarding_permissions,
            onboarding_permissions::request_onboarding_permission,
            local_status,
            local_instances,
            set_up_local,
            use_local,
            open_docker_download,
            docker_install::download_docker,
            docker_install::open_docker,
            finish_onboarding,
            shortcuts::set_shortcut,
            quick_ask::resize_quick_ask,
            quick_ask::hide_quick_ask,
            quick_ask::quick_ask_pinned,
            quick_ask::set_quick_ask_pinned,
            quick_ask::set_quick_ask_picker_open,
            context::take_context_files,
            context::open_accessibility_settings,
            dropped::take_shared,
            device::device_status,
            device::device_link,
            device::device_unlink,
            computer_access::local_allow_computer,
            computer_access::local_revoke_computer,
            local_work::local_grants,
            local_work::local_pick_folder,
            local_work::local_revoke,
            local_work::local_files,
            local_work::local_file,
            local_services::local_services,
            local_services::local_save_service,
            local_services::local_remove_service
        ])
        .manage(PendingSignIn::default())
        .manage(console::Granted::default())
        .manage(screen::ScreenState::default())
        .manage(notify::Delivered::default())
        .manage(activity::Activity::default())
        .manage(shortcuts::Bindings::default())
        .manage(quick_ask::Panels::default())
        .manage(context::CapturedFiles::default())
        .manage(dropped::Dropped::default())
        .manage(device::Device::default())
        .manage(computer_access::Access::default())
        .setup(|app| {
            let handle = app.handle();
            let (mut settings, unreadable) = settings::load_or_quarantine(handle);
            if let Some(typed) = server_argument(std::env::args().skip(1)) {
                match parse_server_url(&typed) {
                    Ok(server) => {
                        settings.server_url = Some(server);
                        if let Err(e) = settings::save(handle, &settings) {
                            eprintln!("{e}");
                        }
                    }
                    Err(e) => eprintln!("--server: {e}"),
                }
            }
            // The organization's server: where the app opens before the person
            // has chosen one, and the only one it opens while it is locked.
            let policy = managed::load();
            if let Some(server) = policy.server_for(settings.server_url.as_ref()) {
                if settings.server_url.as_ref() != Some(&server) {
                    settings.server_url = Some(server);
                    settings.deployment = Some(Deployment::Server);
                    if let Err(e) = settings::save(handle, &settings) {
                        eprintln!("{e}");
                    }
                }
            }
            app.manage(managed::Managed(policy));
            install_menu(handle, &settings)?;
            // Right-click on the Dock icon: "New Chat With" the pinned agents.
            #[cfg(target_os = "macos")]
            pinned::dock::install(handle, &settings.pinned_agents);
            let (start, notice) = console_start(settings.server_url.clone());
            app.manage(StartupNotice(Mutex::new(notice.or(unreadable))));
            app.manage(PendingScreenshot(Mutex::new(None)));
            let reached = matches!(start, WebviewUrl::External(_));
            if let (true, Some(server)) = (reached, settings.server_url.as_ref()) {
                // Before the window loads the console: a page that asks the
                // shell for its state as it mounts must find the grant there.
                start_companions(handle, server, &settings);
            }
            // This computer's own connection, if the person linked it to this
            // server: their runs can reach it whether or not a window is open.
            device::start(handle);
            open_window(handle, start)?;
            shortcuts::register_all(handle, &settings.shortcuts);
            let actions = handle.clone();
            app.notification()
                .on_action(move |performed| notify::on_action(&actions, performed))?;
            // The return leg. A deep link is something any process on this
            // machine can fire, so all it is allowed to do is send the console
            // to one path on the server the user already chose.
            let deep_link_handle = handle.clone();
            app.deep_link().on_open_url(move |event| {
                let links = event.urls();
                for link in &links {
                    match widgets::handle(&deep_link_handle, link) {
                        Ok(true) => return,
                        Ok(false) => {}
                        Err(error) => {
                            eprintln!("widget: {error}");
                            return;
                        }
                    }
                }
                let chosen = settings::load(&deep_link_handle).ok().and_then(|s| s.server_url);
                // The nonce this shell minted when it opened the browser. Taken
                // out of the slot whether the link matches or not: a sign-in is
                // answered once, so a second link carrying the same nonce is a
                // replay and finds nothing.
                let expected = deep_link_handle
                    .state::<PendingSignIn>()
                    .0
                    .lock()
                    .ok()
                    .and_then(|mut slot| slot.take());
                for link in links {
                    if let Some(destination) = deep_link_return(chosen.as_ref(), expected.as_deref(), link.as_str()) {
                        if let Some(console) = deep_link_handle.get_webview_window(WINDOW) {
                            if let Err(e) = console.navigate(destination) {
                                eprintln!("Could not finish signing in: {e}");
                            } else {
                                let _ = console.set_focus();
                            }
                        }
                        break;
                    }
                }
            });
            if let Ok(Some(links)) = app.deep_link().get_current() {
                for link in links {
                    if let Err(error) = widgets::handle(handle, &link) {
                        eprintln!("widget launch: {error}");
                    }
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app, _event| {
            // A click on the Dock icon with the console hidden is a request to see it.
            #[cfg(target_os = "macos")]
            if let RunEvent::Reopen { .. } = _event {
                if let Err(e) = bring_console(_app) {
                    eprintln!("{e}");
                }
            }
            // Files dropped on the Dock icon (or opened with the app): a new chat
            // with them. `Info.plist` declares the app a viewer of any file, which
            // is what lets the Dock take the drop at all.
            #[cfg(target_os = "macos")]
            if let RunEvent::Opened { urls } = &_event {
                let paths = urls.iter().filter_map(|url| url.to_file_path().ok()).collect();
                dropped::receive(_app, paths);
            }
        });
}

#[cfg(test)]
mod tests {
    use std::net::TcpListener;
    use std::time::{Duration, Instant};

    use tauri::Theme;

    use super::{
        appearance, attach_script, loading_color, notify, reachable, Appearance, Look, Url, GO, LOADING_DARK,
        LOADING_LIGHT,
    };

    #[test]
    fn connection_review_keeps_setup_material_until_dashboard_navigation() {
        for path in [
            "/desktop/readiness?connection=1",
            "/pl/desktop/readiness",
            "/desktop/readiness/",
        ] {
            assert!(matches!(
                super::page_surface(&Url::parse(&format!("https://example.com{path}")).unwrap()),
                super::Surface::Setup
            ));
        }
        assert!(matches!(
            super::page_surface(&Url::parse("https://example.com/dashboard").unwrap()),
            super::Surface::Console
        ));
    }

    #[test]
    fn every_new_chat_click_has_an_explicit_distinct_request() {
        let first = super::fresh_chat_path();
        let second = super::fresh_chat_path();
        assert_ne!(first, second);
        for path in [first, second] {
            assert!(super::notify::is_console_path(&path));
            let url = Url::parse("https://example.com").unwrap().join(&path).unwrap();
            assert_eq!(url.path(), "/chat");
            let request = url.query_pairs().find(|(key, _)| key == "new").unwrap().1;
            assert!(uuid::Uuid::parse_str(&request).is_ok());
        }
    }

    #[test]
    fn switching_servers_reuses_both_companion_windows_and_replaces_their_pages() {
        use tauri::test::{mock_builder, mock_context, noop_assets};
        use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

        let app = mock_builder().build(mock_context(noop_assets())).unwrap();
        let previous = Url::parse("https://previous.example/").unwrap();
        let windows = [super::blobby::WINDOW, super::quick_ask::WINDOW].map(|label| {
            WebviewWindowBuilder::new(&app, label, WebviewUrl::External(previous.clone()))
                .build()
                .unwrap()
        });
        for address in [
            "http://localhost:3000/pl/",
            "https://next.example/",
            "http://localhost:3000/",
        ] {
            let server = Url::parse(address).unwrap();
            super::retarget_companions(app.handle(), &server).unwrap();
            for (window, path) in windows.iter().zip([super::blobby::PATH, super::quick_ask::PATH]) {
                assert_eq!(window.url().unwrap(), server.join(path).unwrap());
                assert_eq!(app.get_webview_window(window.label()).unwrap(), *window);
            }
        }
    }

    #[test]
    fn switching_servers_before_companions_exist_leaves_them_for_startup() {
        use tauri::test::{mock_builder, mock_context, noop_assets};
        use tauri::Manager;

        let app = mock_builder().build(mock_context(noop_assets())).unwrap();
        super::retarget_companions(app.handle(), &Url::parse("http://localhost:3000/").unwrap()).unwrap();
        assert!(app.webview_windows().is_empty());
    }

    #[test]
    fn the_server_argument_is_read_in_both_spellings_and_ignored_when_absent() {
        let words = |s: &str| s.split(' ').map(str::to_owned).collect::<Vec<_>>();
        assert_eq!(
            super::server_argument(words("--server http://localhost:3000")).as_deref(),
            Some("http://localhost:3000")
        );
        assert_eq!(
            super::server_argument(words("--server=agenticos.acme.com")).as_deref(),
            Some("agenticos.acme.com")
        );
        assert_eq!(super::server_argument(words("--verbose")), None);
        assert_eq!(super::server_argument(words("--server")), None);
    }

    #[test]
    fn a_pending_screenshot_is_only_for_the_chat_page_on_its_own_server() {
        let chat = Url::parse("http://localhost:3000/chat").unwrap();
        let pending = super::Pending {
            png: vec![],
            chat,
            taken: Instant::now(),
        };
        assert!(pending.is_for(&Url::parse("http://localhost:3000/chat").unwrap()));
        assert!(pending.is_for(&Url::parse("http://localhost:3000/pl/chat").unwrap()));
        assert!(!pending.is_for(&Url::parse("https://evil.example/chat").unwrap()));
        assert!(!pending.is_for(&Url::parse("http://localhost:3001/chat").unwrap()));
        assert!(!pending.is_for(&Url::parse("http://localhost:3000/agents").unwrap()));
    }

    #[test]
    fn a_pending_screenshot_goes_stale_after_its_ttl() {
        let chat = Url::parse("http://localhost:3000/chat").unwrap();
        let taken = Instant::now();
        let pending = super::Pending {
            png: vec![],
            chat,
            taken,
        };
        assert!(!pending.expired(taken + Duration::from_secs(60)));
        assert!(pending.expired(taken + super::PENDING_SCREENSHOT_TTL + Duration::from_secs(1)));
    }

    #[test]
    fn the_title_names_the_host_only_away_from_home() {
        let server = Url::parse("https://agenticos.acme.com/").unwrap();
        let at = |s: &str| super::window_title(&Url::parse(s).unwrap(), Some(&server));
        assert_eq!(at("https://agenticos.acme.com/pl/chat"), "AgenticOS");
        assert_eq!(at("tauri://localhost/settings.html"), "AgenticOS");
        assert_eq!(at("http://tauri.localhost/index.html"), "AgenticOS");
        assert_eq!(
            at("https://accounts.google.com/o/oauth2/auth"),
            "accounts.google.com — AgenticOS"
        );
        assert_eq!(
            super::window_title(&Url::parse("https://x.example/").unwrap(), None),
            "x.example — AgenticOS"
        );
    }

    #[test]
    fn a_port_something_listens_on_is_reachable() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert_eq!(
            reachable(&Url::parse(&format!("http://127.0.0.1:{port}/")).unwrap()),
            Ok(())
        );
    }

    #[test]
    fn a_port_nothing_listens_on_says_so_and_names_the_address() {
        let port = TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let server = Url::parse(&format!("http://127.0.0.1:{port}/")).unwrap();
        let refusal = reachable(&server).unwrap_err();
        assert!(refusal.contains(server.as_str()));
        assert!(refusal.contains("make dev"));
    }

    #[test]
    fn the_attach_script_carries_the_png_and_targets_the_composers_input() {
        let script = attach_script(&[0x89, b'P', b'N', b'G']);
        assert!(script.contains("iVBORw=="));
        assert!(script.contains(r#"input[type="file"][accept*="image/png"]"#));
        assert!(script.contains(r#"type: "image/png""#));
    }

    #[test]
    fn the_console_opens_on_its_dashboard_not_the_sign_in_form() {
        let server = Url::parse("https://agenticos.acme.com/").unwrap();
        assert_eq!(super::home(&server).as_str(), "https://agenticos.acme.com/dashboard");
    }

    #[test]
    fn every_destination_under_go_is_a_page_of_the_console() {
        for (id, _, path, _) in GO {
            assert!(notify::is_console_path(path), "{id}");
        }
    }

    #[test]
    fn the_loading_colour_follows_the_chosen_mode_and_then_the_systems() {
        let mode = |mode| Appearance {
            look: Look::Standard,
            mode,
        };
        assert_eq!(loading_color(mode(appearance::Mode::Dark), Theme::Light), LOADING_DARK);
        assert_eq!(loading_color(mode(appearance::Mode::Light), Theme::Dark), LOADING_LIGHT);
        assert_eq!(loading_color(mode(appearance::Mode::System), Theme::Dark), LOADING_DARK);
    }

    #[test]
    fn a_glass_console_paints_nothing_over_its_material() {
        let glass = Appearance {
            look: Look::Glass,
            mode: appearance::Mode::Dark,
        };
        assert_eq!(loading_color(glass, Theme::Dark).3 == 0, appearance::VIBRANCY);
    }
}
