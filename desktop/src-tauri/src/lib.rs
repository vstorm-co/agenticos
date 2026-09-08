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
use std::sync::Mutex;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::{AppHandle, Emitter, Manager, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder, Wry};

const WINDOW: &str = "main";
const PET: &str = "pet";
const CHANGE_SERVER: &str = "change-server";
const RELOAD: &str = "reload";
const SHOW_PET: &str = "show-pet";
const PET_KIND_EVENT: &str = "pet-kind";
const PET_SIZE: (f64, f64) = (144.0, 184.0);
const PROBE_TIMEOUT: Duration = Duration::from_secs(1);

#[derive(Serialize, Deserialize, Default)]
struct Settings {
    #[serde(default)]
    server_url: Option<Url>,
    #[serde(default)]
    pet: PetSettings,
}

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

/// The menu items whose checkmarks mirror the pet's settings.
struct PetMenu {
    show: CheckMenuItem<Wry>,
    kinds: Vec<(Kind, CheckMenuItem<Wry>)>,
}

impl PetMenu {
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

/// Where the shell's own page lives inside the webview.
///
/// Tauri serves the local `frontendDist` from a custom scheme on macOS and Linux
/// and from a loopback name on Windows, where WebView2 has no custom schemes.
fn connect_page() -> Url {
    let origin = if cfg!(windows) {
        "http://tauri.localhost"
    } else {
        "tauri://localhost"
    };
    Url::parse(&format!("{origin}/index.html")).expect("a literal origin parses")
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

/// Bring the console forward, opening it again if it was closed while the pet stayed.
#[tauri::command]
fn show_console(app: AppHandle) -> Result<(), String> {
    if let Some(console) = app.get_webview_window(WINDOW) {
        return console.set_focus().map_err(|e| e.to_string());
    }
    let settings = load_settings(&app)?;
    let (start, notice) = console_start(settings.server_url);
    if let Ok(mut slot) = app.state::<StartupNotice>().0.lock() {
        *slot = notice;
    }
    open_window(&app, start).map(|_| ()).map_err(|e| e.to_string())
}

/// Put the console on a fresh chat, opening it if it was closed.
///
/// `/chat` with no conversation id is how the console starts a new one, so the
/// pet's button is a navigation, not a request: whether the person may chat, and
/// with which agent, is the console's to decide once it is there.
#[tauri::command]
fn open_chat(app: AppHandle) -> Result<(), String> {
    let settings = load_settings(&app)?;
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
        None => open_window(&app, WebviewUrl::External(chat))
            .map(|_| ())
            .map_err(|e| e.to_string()),
    }
}

fn open_window(app: &AppHandle, url: WebviewUrl) -> tauri::Result<WebviewWindow> {
    WebviewWindowBuilder::new(app, WINDOW, url)
        .title("AgenticOS")
        .inner_size(1280.0, 800.0)
        .min_inner_size(900.0, 600.0)
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
    let reload = MenuItem::with_id(app, RELOAD, "Reload", true, Some("CmdOrCtrl+R"))?;
    let server = Submenu::with_items(app, "Server", true, &[&change_server, &reload])?;

    let show = CheckMenuItem::with_id(app, SHOW_PET, "Show pet", true, pet.enabled, Some("CmdOrCtrl+Shift+P"))?;
    let kinds = Kind::ALL
        .into_iter()
        .map(|kind| {
            let item = CheckMenuItem::with_id(app, kind.menu_id(), kind.label(), true, kind == pet.kind, None::<&str>)?;
            Ok((kind, item))
        })
        .collect::<tauri::Result<Vec<_>>>()?;
    let mut pet_items: Vec<&dyn tauri::menu::IsMenuItem<Wry>> = vec![&show];
    let separator = PredefinedMenuItem::separator(app)?;
    pet_items.push(&separator);
    for (_, item) in &kinds {
        pet_items.push(item);
    }
    let pet_menu = Submenu::with_items(app, "Pet", true, &pet_items)?;

    let menu = Menu::default(app)?;
    menu.insert(&server, 1)?;
    menu.insert(&pet_menu, 2)?;
    app.set_menu(menu)?;
    app.manage(PetMenu { show, kinds });

    app.on_menu_event(|app, event| {
        let id = event.id().as_ref();
        let outcome = match id {
            SHOW_PET => toggle_pet(app),
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
        .invoke_handler(tauri::generate_handler![
            server_url,
            startup_notice,
            connect,
            page_error,
            pet_settings,
            save_pet_position,
            show_console,
            open_chat
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
            open_window(handle, start)?;
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

    use super::{parse_server_url, reachable, Kind, PetSettings, Settings, Url};

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
        let raw = serde_json::to_string(&Settings { server_url: None, pet }).unwrap();
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
