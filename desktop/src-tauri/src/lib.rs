//! A window around a deployment's console, and a pet that keeps it company.
//!
//! The console itself stays on the server: this shell holds one setting, the
//! address of that server, and points its webview at it. The first launch, and
//! "Change server…" afterwards, show a local page asking for the address;
//! everything after that is the same Next.js application a browser would load,
//! with the same cookies, the same permissions and the same tenant checks.
//!
//! The pet is a second, transparent, always-on-top window drawing a pixel-art
//! sprite. It can be dragged anywhere, clicked, and tucked away from the menu;
//! where it was left and which look it wears are remembered beside the server.

use std::fs;
use std::io::ErrorKind;
use std::net::{TcpStream, ToSocketAddrs};
use std::path::PathBuf;
use std::str::FromStr;
use std::sync::Mutex;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use base64::Engine;

use serde::{Deserialize, Serialize};
use tauri::menu::{CheckMenuItem, ContextMenu, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::webview::PageLoadEvent;
use tauri::{AppHandle, Emitter, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Wry};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

const WINDOW: &str = "main";
const PET: &str = "pet";
const CHANGE_SERVER: &str = "change-server";
const RELOAD: &str = "reload";
const SHORTCUTS: &str = "shortcuts";
const SCREENSHOT_CHAT: &str = "screenshot-chat";
const DEFAULT_SCREENSHOT_SHORTCUT: &str = "CmdOrCtrl+Shift+A";
const SHOW_PET: &str = "show-pet";
const NEW_CHAT: &str = "new-chat";
const OPEN_CONSOLE: &str = "open-console";
const PET_KIND_EVENT: &str = "pet-kind";
const PET_SIZE: (f64, f64) = (144.0, 184.0);
const PROBE_TIMEOUT: Duration = Duration::from_secs(1);

#[derive(Serialize, Deserialize, Default)]
struct Settings {
    #[serde(default)]
    server_url: Option<Url>,
    #[serde(default)]
    pet: PetSettings,
    #[serde(default)]
    shortcuts: Shortcuts,
}

/// Global shortcuts, as accelerators the shortcut plugin parses (`CmdOrCtrl+Shift+A`).
/// `None` is a shortcut somebody switched off.
#[derive(Serialize, Deserialize, Clone)]
struct Shortcuts {
    #[serde(default = "default_screenshot_shortcut")]
    screenshot_chat: Option<String>,
}

fn default_screenshot_shortcut() -> Option<String> {
    Some(DEFAULT_SCREENSHOT_SHORTCUT.to_owned())
}

impl Default for Shortcuts {
    fn default() -> Self {
        Self {
            screenshot_chat: default_screenshot_shortcut(),
        }
    }
}

/// A screenshot taken for a chat that is still loading; the console's page-load
/// hook takes it once `/chat` has finished loading.
struct PendingScreenshot(Mutex<Option<Vec<u8>>>);

#[derive(Serialize, Deserialize, Clone)]
struct PetSettings {
    #[serde(default = "shown_by_default")]
    enabled: bool,
    #[serde(default)]
    kind: Kind,
    #[serde(default)]
    position: Option<Position>,
}

fn shown_by_default() -> bool {
    true
}

impl Default for PetSettings {
    fn default() -> Self {
        Self {
            enabled: true,
            kind: Kind::default(),
            position: None,
        }
    }
}

#[derive(Serialize, Deserialize, Clone, Copy)]
struct Position {
    x: f64,
    y: f64,
}

/// Which pet it is. Each is an entry in `PETS` in `ui/pet-sprites.js` under the same name.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Default, Debug)]
#[serde(rename_all = "lowercase")]
enum Kind {
    #[default]
    Orbit,
    Boxy,
    Ghost,
    Sprout,
    Amigo,
}

impl Kind {
    const ALL: [Kind; 5] = [Kind::Orbit, Kind::Boxy, Kind::Ghost, Kind::Sprout, Kind::Amigo];

    fn label(self) -> &'static str {
        match self {
            Kind::Orbit => "Orbit",
            Kind::Boxy => "Boxy",
            Kind::Ghost => "Ghost",
            Kind::Sprout => "Sprout",
            Kind::Amigo => "Amigo",
        }
    }

    fn menu_id(self) -> &'static str {
        match self {
            Kind::Orbit => "pet-orbit",
            Kind::Boxy => "pet-boxy",
            Kind::Ghost => "pet-ghost",
            Kind::Sprout => "pet-sprout",
            Kind::Amigo => "pet-amigo",
        }
    }

    fn from_menu_id(id: &str) -> Option<Kind> {
        Kind::ALL.into_iter().find(|kind| kind.menu_id() == id)
    }
}

/// Why the console opened on the connect page although a server was stored.
///
/// Read once by that page, which shows it above the form; a blank webview is what
/// an unreachable server looks like otherwise, and it says nothing.
struct StartupNotice(Mutex<Option<String>>);

/// The pet's menu items, shared by the menu bar, the tray icon and the pet's own
/// right-click menu, so one `set_checked` reaches all three.
struct PetMenu {
    show: CheckMenuItem<Wry>,
    kinds: Vec<(Kind, CheckMenuItem<Wry>)>,
    new_chat: MenuItem<Wry>,
    screenshot: MenuItem<Wry>,
    open_console: MenuItem<Wry>,
}

impl PetMenu {
    fn build(app: &AppHandle, pet: &PetSettings) -> tauri::Result<Self> {
        let show = CheckMenuItem::with_id(app, SHOW_PET, "Show pet", true, pet.enabled, Some("CmdOrCtrl+Shift+P"))?;
        let kinds = Kind::ALL
            .into_iter()
            .map(|kind| {
                let item =
                    CheckMenuItem::with_id(app, kind.menu_id(), kind.label(), true, kind == pet.kind, None::<&str>)?;
                Ok((kind, item))
            })
            .collect::<tauri::Result<Vec<_>>>()?;
        let new_chat = MenuItem::with_id(app, NEW_CHAT, "New chat", true, None::<&str>)?;
        let screenshot = MenuItem::with_id(app, SCREENSHOT_CHAT, "Screenshot to new chat", true, None::<&str>)?;
        let open_console = MenuItem::with_id(app, OPEN_CONSOLE, "Open console", true, None::<&str>)?;
        Ok(Self {
            show,
            kinds,
            new_chat,
            screenshot,
            open_console,
        })
    }

    /// The items in menu order; a fresh `Menu` or `Submenu` is built from them each time.
    fn items(&self, app: &AppHandle) -> tauri::Result<Vec<Box<dyn IsMenuItem<Wry>>>> {
        let mut items: Vec<Box<dyn IsMenuItem<Wry>>> = vec![
            Box::new(self.new_chat.clone()),
            Box::new(self.screenshot.clone()),
            Box::new(self.open_console.clone()),
        ];
        items.push(Box::new(PredefinedMenuItem::separator(app)?));
        for (_, item) in &self.kinds {
            items.push(Box::new(item.clone()));
        }
        items.push(Box::new(PredefinedMenuItem::separator(app)?));
        items.push(Box::new(self.show.clone()));
        Ok(items)
    }

    fn menu(&self, app: &AppHandle) -> tauri::Result<Menu<Wry>> {
        let items = self.items(app)?;
        Menu::with_items(app, &items.iter().map(|item| item.as_ref()).collect::<Vec<_>>())
    }

    fn submenu(&self, app: &AppHandle) -> tauri::Result<Submenu<Wry>> {
        let items = self.items(app)?;
        Submenu::with_items(
            app,
            "Pet",
            true,
            &items.iter().map(|item| item.as_ref()).collect::<Vec<_>>(),
        )
    }

    fn reflect(&self, pet: &PetSettings) -> tauri::Result<()> {
        self.show.set_checked(pet.enabled)?;
        for (kind, item) in &self.kinds {
            item.set_checked(*kind == pet.kind)?;
        }
        Ok(())
    }
}

fn settings_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_config_dir()
        .map_err(|e| format!("No configuration directory for this account: {e}"))?;
    Ok(dir.join("server.json"))
}

fn load_settings(app: &AppHandle) -> Result<Settings, String> {
    let path = settings_path(app)?;
    let raw = match fs::read_to_string(&path) {
        Ok(raw) => raw,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(Settings::default()),
        Err(e) => return Err(format!("Cannot read {}: {e}", path.display())),
    };
    serde_json::from_str(&raw).map_err(|e| format!("{} is not a saved shell configuration: {e}", path.display()))
}

fn save_settings(app: &AppHandle, settings: &Settings) -> Result<(), String> {
    let path = settings_path(app)?;
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir).map_err(|e| format!("Cannot create {}: {e}", dir.display()))?;
    }
    let raw = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    fs::write(&path, raw).map_err(|e| format!("Cannot write {}: {e}", path.display()))
}

/// The address a person typed, as the URL the webview will be pointed at.
///
/// A bare host is the common spelling (`agenticos.acme.com`), so a missing scheme
/// means `https`. Anything that is not a web address is refused here rather than
/// handed to the webview, which would show a platform error page with no way back
/// except the menu.
fn parse_server_url(typed: &str) -> Result<Url, String> {
    let typed = typed.trim();
    if typed.is_empty() {
        return Err("Enter the address of your AgenticOS server.".to_owned());
    }
    let spelled = if typed.contains("://") {
        typed.to_owned()
    } else {
        format!("https://{typed}")
    };
    let url = Url::parse(&spelled).map_err(|_| format!("{typed} is not a web address."))?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(format!(
            "{typed} is not a web address: the shell opens http and https servers."
        ));
    }
    if url.host_str().is_none() {
        return Err(format!("{typed} names no host."));
    }
    Ok(url)
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

/// Show one of the shell's pages in the console window, opening the window if it is closed.
fn show_local_page(app: &AppHandle, name: &str) -> Result<(), String> {
    match app.get_webview_window(WINDOW) {
        Some(console) => {
            console.navigate(local_page(name)).map_err(|e| e.to_string())?;
            console.set_focus().map_err(|e| e.to_string())
        }
        None => open_window(app, WebviewUrl::App(name.into()))
            .map(|_| ())
            .map_err(|e| e.to_string()),
    }
}

/// Whether something is listening where the address points.
///
/// A TCP connect, not an HTTP request: the question is "is the stack up", and the
/// answer has to come back before the window shows anything. WebKit renders a
/// refused connection as a blank white page, which is indistinguishable from a
/// console that has not painted yet.
fn reachable(server: &Url) -> Result<(), String> {
    let host = server.host_str().ok_or_else(|| format!("{server} names no host."))?;
    let port = server
        .port_or_known_default()
        .ok_or_else(|| format!("{server} names no port."))?;
    let nothing_answers =
        || format!("Nothing answers at {server}. Start the stack (`make dev`) or change the address.");
    let addrs = (host, port).to_socket_addrs().map_err(|_| nothing_answers())?;
    for addr in addrs {
        if TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).is_ok() {
            return Ok(());
        }
    }
    Err(nothing_answers())
}

/// The stored server when it answers; otherwise the connect page, with the reason.
fn console_start(server: Option<Url>) -> (WebviewUrl, Option<String>) {
    match server {
        Some(server) => match reachable(&server) {
            Ok(()) => (WebviewUrl::External(server), None),
            Err(notice) => (WebviewUrl::App("index.html".into()), Some(notice)),
        },
        None => (WebviewUrl::App("index.html".into()), None),
    }
}

#[tauri::command]
fn server_url(app: AppHandle) -> Result<Option<Url>, String> {
    Ok(load_settings(&app)?.server_url)
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
    let mut settings = load_settings(&app)?;
    settings.server_url = Some(server.clone());
    save_settings(&app, &settings)?;
    window.navigate(server).map_err(|e| e.to_string())
}

#[tauri::command]
fn shortcuts(app: AppHandle) -> Result<Shortcuts, String> {
    Ok(load_settings(&app)?.shortcuts)
}

/// Rebind, or switch off, the screenshot shortcut. Answers with what is now bound.
///
/// The old binding is released first and put back if the new one cannot be taken,
/// so a combination another application holds leaves the shell where it was.
#[tauri::command]
fn set_screenshot_shortcut(app: AppHandle, accelerator: Option<String>) -> Result<Option<String>, String> {
    let mut settings = load_settings(&app)?;
    let wanted = accelerator.map(|a| a.trim().to_owned()).filter(|a| !a.is_empty());
    let current = settings.shortcuts.screenshot_chat.clone();
    if let Some(old) = &current {
        unregister_shortcut(&app, old);
    }
    if let Some(new) = &wanted {
        if let Err(refusal) = register_screenshot_shortcut(&app, new) {
            if let Some(old) = &current {
                if let Err(e) = register_screenshot_shortcut(&app, old) {
                    eprintln!("could not put {old} back: {e}");
                }
            }
            return Err(refusal);
        }
    }
    settings.shortcuts.screenshot_chat = wanted.clone();
    save_settings(&app, &settings)?;
    Ok(wanted)
}

/// Leave a shell page for the console - the stored server, or the connect form.
#[tauri::command]
fn back_to_console(app: AppHandle, window: WebviewWindow) -> Result<(), String> {
    let settings = load_settings(&app)?;
    let (start, notice) = console_start(settings.server_url);
    if let Ok(mut slot) = app.state::<StartupNotice>().0.lock() {
        *slot = notice;
    }
    let url = match start {
        WebviewUrl::External(url) => url,
        _ => connect_page(),
    };
    window.navigate(url).map_err(|e| e.to_string())
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

#[tauri::command]
fn pet_settings(app: AppHandle) -> Result<PetSettings, String> {
    Ok(load_settings(&app)?.pet)
}

#[tauri::command]
fn save_pet_position(app: AppHandle, x: f64, y: f64) -> Result<(), String> {
    let mut settings = load_settings(&app)?;
    settings.pet.position = Some(Position { x, y });
    save_settings(&app, &settings)
}

/// The pet's own menu, under the right mouse button - the menu bar is far from a
/// pet in the corner of the screen, and on Windows and Linux there is no app menu
/// while the console window is closed.
#[tauri::command]
fn pet_menu(app: AppHandle, window: WebviewWindow) -> Result<(), String> {
    let menu = app.state::<PetMenu>().menu(&app).map_err(|e| e.to_string())?;
    menu.popup(window.as_ref().window()).map_err(|e| e.to_string())
}

/// Bring the console forward, opening it again if it was closed while the pet stayed.
#[tauri::command]
fn show_console(app: AppHandle) -> Result<(), String> {
    bring_console(&app)
}

fn bring_console(app: &AppHandle) -> Result<(), String> {
    if let Some(console) = app.get_webview_window(WINDOW) {
        return console.set_focus().map_err(|e| e.to_string());
    }
    let settings = load_settings(app)?;
    let (start, notice) = console_start(settings.server_url);
    if let Ok(mut slot) = app.state::<StartupNotice>().0.lock() {
        *slot = notice;
    }
    open_window(app, start).map(|_| ()).map_err(|e| e.to_string())
}

/// Put the console on a fresh chat, opening it if it was closed.
///
/// `/chat` with no conversation id is how the console starts a new one, so the
/// pet's button is a navigation, not a request: whether the person may chat, and
/// with which agent, is the console's to decide once it is there.
#[tauri::command]
fn open_chat(app: AppHandle) -> Result<(), String> {
    start_chat(&app)
}

fn start_chat(app: &AppHandle) -> Result<(), String> {
    let settings = load_settings(app)?;
    let server = settings
        .server_url
        .ok_or("No server yet - connect the console to one first.")?;
    reachable(&server)?;
    let chat = server.join("chat").map_err(|e| e.to_string())?;
    match app.get_webview_window(WINDOW) {
        Some(console) => {
            console.navigate(chat).map_err(|e| e.to_string())?;
            console.set_focus().map_err(|e| e.to_string())
        }
        None => open_window(app, WebviewUrl::External(chat))
            .map(|_| ())
            .map_err(|e| e.to_string()),
    }
}

/// Let the person pick a region, and hand back the PNG - or nothing, if they pressed Escape.
///
/// `screencapture -i` is the same crosshair Cmd+Shift+4 gives, silent, into a
/// file of ours. The first time, macOS asks whether AgenticOS may record the
/// screen; refused, it hands back the desktop picture rather than an error.
#[cfg(target_os = "macos")]
fn capture_screen() -> Result<Option<Vec<u8>>, String> {
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
/// attaches what was captured.
fn screenshot_to_chat(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let bytes = match capture_screen() {
            Ok(Some(bytes)) => bytes,
            Ok(None) => return,
            Err(e) => {
                eprintln!("screenshot: {e}");
                return;
            }
        };
        if let Ok(mut slot) = app.state::<PendingScreenshot>().0.lock() {
            *slot = Some(bytes);
        }
        let handle = app.clone();
        let dispatched = app.run_on_main_thread(move || {
            #[cfg(target_os = "macos")]
            if let Err(e) = handle.show() {
                eprintln!("screenshot: {e}");
            }
            if let Err(e) = start_chat(&handle) {
                eprintln!("screenshot: {e}");
            }
        });
        if let Err(e) = dispatched {
            eprintln!("screenshot: {e}");
        }
    });
}

fn register_screenshot_shortcut(app: &AppHandle, accelerator: &str) -> Result<(), String> {
    let shortcut = Shortcut::from_str(accelerator).map_err(|e| format!("{accelerator} is not a shortcut: {e}"))?;
    app.global_shortcut()
        .on_shortcut(shortcut, |app, _shortcut, event| {
            if event.state == ShortcutState::Pressed {
                screenshot_to_chat(app);
            }
        })
        .map_err(|e| format!("Cannot bind {accelerator}: {e}"))
}

fn unregister_shortcut(app: &AppHandle, accelerator: &str) {
    if let Err(e) = app.global_shortcut().unregister(accelerator) {
        eprintln!("could not release {accelerator}: {e}");
    }
}

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    WebviewWindowBuilder::new(app, WINDOW, url)
        .title("AgenticOS")
        .inner_size(1280.0, 800.0)
        .min_inner_size(900.0, 600.0)
        .on_page_load(|window, payload| {
            if !matches!(payload.event(), PageLoadEvent::Finished) || !payload.url().path().ends_with("/chat") {
                return;
            }
            let pending = window
                .app_handle()
                .state::<PendingScreenshot>()
                .0
                .lock()
                .ok()
                .and_then(|mut slot| slot.take());
            if let Some(png) = pending {
                if let Err(e) = window.eval(attach_script(&png)) {
                    eprintln!("screenshot: could not attach: {e}");
                }
            }
        })
        .build()
}

/// Bottom-right of the primary monitor, clear of a dock or taskbar, for a pet never placed yet.
fn default_pet_position(app: &AppHandle) -> Option<(f64, f64)> {
    let monitor = app.primary_monitor().ok()??;
    let scale = monitor.scale_factor();
    let size = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    Some((
        origin.x + size.width - PET_SIZE.0 - 48.0,
        origin.y + size.height - PET_SIZE.1 - 96.0,
    ))
}

fn open_pet(app: &AppHandle, pet: &PetSettings) -> tauri::Result<WebviewWindow> {
    let mut builder = WebviewWindowBuilder::new(app, PET, WebviewUrl::App("pet.html".into()))
        .title("AgenticOS pet")
        .inner_size(PET_SIZE.0, PET_SIZE.1)
        .transparent(true)
        .decorations(false)
        .shadow(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .accept_first_mouse(true);
    if let Some((x, y)) = pet.position.map(|p| (p.x, p.y)).or_else(|| default_pet_position(app)) {
        builder = builder.position(x, y);
    }
    builder.build()
}

fn toggle_pet(app: &AppHandle) -> Result<(), String> {
    let mut settings = load_settings(app)?;
    match app.get_webview_window(PET) {
        Some(pet) => {
            pet.close().map_err(|e| e.to_string())?;
            settings.pet.enabled = false;
        }
        None => {
            open_pet(app, &settings.pet).map_err(|e| e.to_string())?;
            settings.pet.enabled = true;
        }
    }
    save_settings(app, &settings)?;
    app.state::<PetMenu>().reflect(&settings.pet).map_err(|e| e.to_string())
}

fn set_pet_kind(app: &AppHandle, kind: Kind) -> Result<(), String> {
    let mut settings = load_settings(app)?;
    settings.pet.kind = kind;
    save_settings(app, &settings)?;
    app.state::<PetMenu>()
        .reflect(&settings.pet)
        .map_err(|e| e.to_string())?;
    app.emit_to(PET, PET_KIND_EVENT, kind).map_err(|e| e.to_string())
}

fn install_menu(app: &AppHandle, pet: &PetSettings) -> tauri::Result<()> {
    let change_server = MenuItem::with_id(app, CHANGE_SERVER, "Change server…", true, None::<&str>)?;
    let shortcuts = MenuItem::with_id(app, SHORTCUTS, "Shortcuts…", true, None::<&str>)?;
    let reload = MenuItem::with_id(app, RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?;
    let server = Submenu::with_items(app, "Shell", true, &[&change_server, &shortcuts, &reload])?;

    let pet_menu = PetMenu::build(app, pet)?;
    let menu = Menu::default(app)?;
    menu.insert(&server, 1)?;
    menu.insert(&pet_menu.submenu(app)?, 2)?;
    app.set_menu(menu)?;

    let tray_menu = pet_menu.menu(app)?;
    let mut tray = TrayIconBuilder::new()
        .menu(&tray_menu)
        .show_menu_on_left_click(true)
        .tooltip("AgenticOS");
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    app.manage(pet_menu);

    app.on_menu_event(|app, event| {
        let id = event.id().as_ref();
        let outcome = match id {
            SHOW_PET => toggle_pet(app),
            NEW_CHAT => start_chat(app),
            OPEN_CONSOLE => bring_console(app),
            SHORTCUTS => show_local_page(app, "shortcuts.html"),
            SCREENSHOT_CHAT => {
                screenshot_to_chat(app);
                Ok(())
            }
            CHANGE_SERVER | RELOAD => match app.get_webview_window(WINDOW) {
                Some(console) if id == RELOAD => console.eval("location.reload()").map_err(|e| e.to_string()),
                Some(console) => console.navigate(connect_page()).map_err(|e| e.to_string()),
                None => Ok(()),
            },
            other => match Kind::from_menu_id(other) {
                Some(kind) => set_pet_kind(app, kind),
                None => Ok(()),
            },
        };
        if let Err(e) = outcome {
            eprintln!("menu action {id} failed: {e}");
        }
    });
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            server_url,
            startup_notice,
            connect,
            page_error,
            pet_settings,
            save_pet_position,
            show_console,
            open_chat,
            pet_menu,
            shortcuts,
            set_screenshot_shortcut,
            back_to_console
        ])
        .setup(|app| {
            let handle = app.handle();
            let settings = load_settings(handle).unwrap_or_else(|e| {
                eprintln!("{e}");
                Settings::default()
            });
            install_menu(handle, &settings.pet)?;
            let (start, notice) = console_start(settings.server_url);
            app.manage(StartupNotice(Mutex::new(notice)));
            app.manage(PendingScreenshot(Mutex::new(None)));
            open_window(handle, start)?;
            if let Some(accelerator) = &settings.shortcuts.screenshot_chat {
                if let Err(e) = register_screenshot_shortcut(handle, accelerator) {
                    eprintln!("{e}");
                }
            }
            if settings.pet.enabled {
                open_pet(handle, &settings.pet)?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use std::net::TcpListener;
    use std::str::FromStr;

    use super::{
        attach_script, parse_server_url, reachable, Kind, PetSettings, Settings, Shortcuts, Url,
        DEFAULT_SCREENSHOT_SHORTCUT,
    };

    #[test]
    fn a_bare_host_is_opened_over_https() {
        assert_eq!(
            parse_server_url("agenticos.acme.com").unwrap().as_str(),
            "https://agenticos.acme.com/"
        );
    }

    #[test]
    fn a_scheme_and_port_are_kept_as_typed() {
        assert_eq!(
            parse_server_url(" http://localhost:3000 ").unwrap().as_str(),
            "http://localhost:3000/"
        );
    }

    #[test]
    fn an_empty_address_is_refused() {
        assert!(parse_server_url("   ").is_err());
    }

    #[test]
    fn a_scheme_the_webview_cannot_open_is_refused() {
        assert!(parse_server_url("ftp://files.acme.com").is_err());
    }

    #[test]
    fn a_scheme_with_no_host_is_refused() {
        assert!(parse_server_url("https://").is_err());
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
    fn a_configuration_saved_before_shortcuts_existed_gets_the_default_binding() {
        let settings: Settings = serde_json::from_str(r#"{"server_url":"https://agenticos.acme.com/"}"#).unwrap();
        assert_eq!(
            settings.shortcuts.screenshot_chat.as_deref(),
            Some(DEFAULT_SCREENSHOT_SHORTCUT)
        );
    }

    #[test]
    fn a_shortcut_switched_off_stays_off() {
        let raw = serde_json::to_string(&Shortcuts { screenshot_chat: None }).unwrap();
        let back: Shortcuts = serde_json::from_str(&raw).unwrap();
        assert!(back.screenshot_chat.is_none());
    }

    #[test]
    fn the_default_binding_parses_as_a_shortcut() {
        assert!(super::Shortcut::from_str(DEFAULT_SCREENSHOT_SHORTCUT).is_ok());
    }

    #[test]
    fn the_attach_script_carries_the_png_and_targets_the_composers_input() {
        let script = attach_script(&[0x89, b'P', b'N', b'G']);
        assert!(script.contains("iVBORw=="));
        assert!(script.contains(r#"input[type="file"][accept*="image/png"]"#));
        assert!(script.contains(r#"type: "image/png""#));
    }

    #[test]
    fn a_configuration_saved_before_the_pet_existed_still_loads_with_the_pet_shown() {
        let settings: Settings = serde_json::from_str(r#"{"server_url":"https://agenticos.acme.com/"}"#).unwrap();
        assert_eq!(settings.server_url.unwrap().as_str(), "https://agenticos.acme.com/");
        assert!(settings.pet.enabled);
        assert_eq!(settings.pet.kind, Kind::Orbit);
        assert!(settings.pet.position.is_none());
    }

    #[test]
    fn a_tucked_away_pet_with_a_look_and_a_place_round_trips() {
        let pet = PetSettings {
            enabled: false,
            kind: Kind::Ghost,
            position: Some(super::Position { x: 12.5, y: 700.0 }),
        };
        let raw = serde_json::to_string(&Settings {
            server_url: None,
            pet,
            shortcuts: Shortcuts::default(),
        })
        .unwrap();
        let back: Settings = serde_json::from_str(&raw).unwrap();
        assert!(!back.pet.enabled);
        assert_eq!(back.pet.kind, Kind::Ghost);
        assert_eq!(back.pet.position.unwrap().y, 700.0);
        assert!(raw.contains(r#""kind":"ghost""#));
    }

    #[test]
    fn every_pet_has_a_menu_entry_that_resolves_back_to_it() {
        for kind in Kind::ALL {
            assert_eq!(Kind::from_menu_id(kind.menu_id()), Some(kind));
        }
        assert_eq!(Kind::from_menu_id("show-pet"), None);
    }
}
