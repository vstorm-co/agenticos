//! Blobby: the creature that sits on the desktop beside the console.
//!
//! It replaced the pixel pets. The window is the shell's - transparent, always on
//! top, on every workspace - and what is drawn in it is a page of the console,
//! `/desktop/blobby`, so it wears the same `blobatar` faces the agents do, can
//! wear one of your agents' faces, and reads what your agents are doing with the
//! console's own session rather than with a credential of the shell's.
//!
//! Who it is, whether it is shown and where it was left are the shell's to keep:
//! the menu picks from the cast, and the menu works while no page is loaded.

use std::sync::OnceLock;

use serde::{Deserialize, Serialize};
use tauri::menu::{CheckMenuItem, IsMenuItem, MenuItem, Submenu};
use tauri::{AppHandle, DragDropEvent, Emitter, Manager, Url, WebviewUrl, WebviewWindow, WindowEvent, Wry};

use crate::{appearance, dropped};

pub const WINDOW: &str = "blobby";
pub const PATH: &str = "desktop/blobby";
pub const SETTINGS_EVENT: &str = "desktop:blobby";
pub const SAY_EVENT: &str = "desktop:say";
/// A file dragged over blobby (`"enter"`), for it to say it will take it.
pub const DROP_EVENT: &str = "desktop:blobby-drop";
pub const SHOW_MENU_ID: &str = "show-blobby";
pub const CUSTOMIZE_MENU_ID: &str = "customize-blobby";
const CAST_MENU_PREFIX: &str = "blobby-cast-";
/// The sizes the menu offers; anything between them is a pinch away.
pub const SIZES: [(&str, &str, f64); 3] = [
    ("blobby-size-small", "Small", 0.75),
    ("blobby-size-medium", "Medium", 1.0),
    ("blobby-size-large", "Large", 1.35),
];
/// Room for the creature at its natural size and, above it, a speech bubble of two short lines.
const SIZE: (f64, f64) = (200.0, 232.0);
/// How small and how large it may be made, as a multiple of its natural size.
pub const SCALE_RANGE: (f64, f64) = (0.6, 1.6);

/// The window for blobby at a scale, kept inside the range.
pub fn window_size(scale: f64) -> (f64, f64) {
    let scale = clamp_scale(scale);
    (SIZE.0 * scale, SIZE.1 * scale)
}

pub fn clamp_scale(scale: f64) -> f64 {
    if scale.is_finite() {
        scale.clamp(SCALE_RANGE.0, SCALE_RANGE.1)
    } else {
        1.0
    }
}

/// The cast, read from the file the console renders it from, so the menu and the
/// settings page cannot offer different creatures under one name.
const CAST_JSON: &str = include_str!("../../../frontend/src/lib/desktop/blobby-cast.json");

#[derive(Deserialize, Debug)]
pub struct CastMember {
    pub id: String,
    pub name: String,
}

pub fn cast() -> &'static [CastMember] {
    static CAST: OnceLock<Vec<CastMember>> = OnceLock::new();
    CAST.get_or_init(|| serde_json::from_str(CAST_JSON).expect("blobby-cast.json is a list of {id, name}"))
}

/// Who blobby is: one of the cast, the face of one of your agents, or a face of
/// your own, drawn from a seed of your choosing in one of the avatar colours.
#[derive(Serialize, Deserialize, Clone, PartialEq, Eq, Debug)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum Character {
    Cast {
        id: String,
    },
    Agent {
        agent_id: String,
        slug: String,
        name: String,
        color_slot: Option<u8>,
    },
    Custom {
        seed: String,
        color_slot: Option<u8>,
    },
}

impl Default for Character {
    fn default() -> Self {
        Character::Cast {
            id: cast()[0].id.clone(),
        }
    }
}

/// How often it speaks unprompted. What the agents are doing is said regardless.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Default, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Chatter {
    Quiet,
    #[default]
    Normal,
    Chatty,
}

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Debug)]
pub struct Position {
    pub x: f64,
    pub y: f64,
}

#[derive(Serialize, Deserialize, Clone, PartialEq, Debug)]
pub struct BlobbySettings {
    #[serde(default = "shown_by_default")]
    pub enabled: bool,
    #[serde(default)]
    pub character: Character,
    #[serde(default)]
    pub chatter: Chatter,
    /// Bubbles about runs, approvals and questions; off leaves it company only.
    #[serde(default = "shown_by_default")]
    pub activity: bool,
    /// Whether it strolls along the bottom of the screen when idle.
    #[serde(default = "shown_by_default")]
    pub roams: bool,
    /// How big it is, as a multiple of its natural size (`SCALE_RANGE`).
    #[serde(default = "natural_size")]
    pub size: f64,
    #[serde(default)]
    pub position: Option<Position>,
}

fn shown_by_default() -> bool {
    true
}

fn natural_size() -> f64 {
    1.0
}

impl Default for BlobbySettings {
    fn default() -> Self {
        Self {
            enabled: true,
            character: Character::default(),
            chatter: Chatter::default(),
            activity: true,
            roams: true,
            size: 1.0,
            position: None,
        }
    }
}

const MAX_ID: usize = 64;
const MAX_NAME: usize = 200;

/// Check a character sent by a page before it is stored and handed to another.
///
/// The page is the console and trusted to mean well, but what it sends is kept in
/// a file and rendered again later, so its bounds are checked here rather than
/// assumed: a cast member that exists, ids and names of a sane length, and a
/// colour slot from the avatar ramp.
pub fn validate(character: &Character) -> Result<(), String> {
    let slot_ok = |slot: &Option<u8>| slot.map_or(true, |s| (1..=10).contains(&s));
    let sized = |value: &str, max: usize| !value.trim().is_empty() && value.chars().count() <= max;
    match character {
        Character::Cast { id } if cast().iter().any(|member| &member.id == id) => Ok(()),
        Character::Cast { id } => Err(format!("{id} is not one of the cast.")),
        Character::Agent {
            agent_id,
            slug,
            name,
            color_slot,
        } if sized(agent_id, MAX_ID) && sized(slug, MAX_NAME) && sized(name, MAX_NAME) && slot_ok(color_slot) => Ok(()),
        Character::Agent { .. } => Err("That agent cannot be blobby's face.".to_owned()),
        Character::Custom { seed, color_slot } if sized(seed, MAX_ID) && slot_ok(color_slot) => Ok(()),
        Character::Custom { .. } => Err("A face of your own needs a name of up to 64 characters.".to_owned()),
    }
}

/// Blobby's items, shared by the menu bar and the tray, so one `set_checked`
/// reaches both.
pub struct BlobbyMenu {
    show: CheckMenuItem<Wry>,
    cast: Vec<(String, CheckMenuItem<Wry>)>,
    sizes: Vec<(f64, CheckMenuItem<Wry>)>,
    customize: MenuItem<Wry>,
}

/// The menu's size closest to a scale - a pinch lands between them.
fn nearest_size(scale: f64) -> f64 {
    SIZES
        .iter()
        .map(|(_, _, size)| *size)
        .min_by(|a, b| (a - scale).abs().total_cmp(&(b - scale).abs()))
        .unwrap_or(1.0)
}

/// The size a menu id names, if it names one.
pub fn size_from_menu_id(id: &str) -> Option<f64> {
    SIZES
        .iter()
        .find(|(menu_id, ..)| *menu_id == id)
        .map(|(_, _, size)| *size)
}

impl BlobbyMenu {
    pub fn build(app: &AppHandle, blobby: &BlobbySettings) -> tauri::Result<Self> {
        let show = CheckMenuItem::with_id(
            app,
            SHOW_MENU_ID,
            "Show blobby",
            true,
            blobby.enabled,
            Some("CmdOrCtrl+Shift+B"),
        )?;
        let cast = cast()
            .iter()
            .map(|member| {
                let item = CheckMenuItem::with_id(
                    app,
                    format!("{CAST_MENU_PREFIX}{}", member.id),
                    &member.name,
                    true,
                    is_cast(&blobby.character, &member.id),
                    None::<&str>,
                )?;
                Ok((member.id.clone(), item))
            })
            .collect::<tauri::Result<Vec<_>>>()?;
        let nearest = nearest_size(blobby.size);
        let sizes = SIZES
            .iter()
            .map(|(id, label, size)| {
                let item = CheckMenuItem::with_id(app, *id, *label, true, *size == nearest, None::<&str>)?;
                Ok((*size, item))
            })
            .collect::<tauri::Result<Vec<_>>>()?;
        let customize = MenuItem::with_id(app, CUSTOMIZE_MENU_ID, "Customize blobby…", true, None::<&str>)?;
        Ok(Self {
            show,
            cast,
            sizes,
            customize,
        })
    }

    pub fn submenu(&self, app: &AppHandle) -> tauri::Result<Submenu<Wry>> {
        let separator = tauri::menu::PredefinedMenuItem::separator(app)?;
        let separator_two = tauri::menu::PredefinedMenuItem::separator(app)?;
        let size_items: Vec<&dyn IsMenuItem<Wry>> = self
            .sizes
            .iter()
            .map(|(_, item)| item as &dyn IsMenuItem<Wry>)
            .collect();
        let size = Submenu::with_items(app, "Size", true, &size_items)?;
        let mut items: Vec<&dyn IsMenuItem<Wry>> = vec![&self.show, &size, &separator];
        for (_, item) in &self.cast {
            items.push(item);
        }
        items.push(&separator_two);
        items.push(&self.customize);
        Submenu::with_items(app, "Blobby", true, &items)
    }

    pub fn reflect(&self, blobby: &BlobbySettings) -> tauri::Result<()> {
        self.show.set_checked(blobby.enabled)?;
        for (id, item) in &self.cast {
            item.set_checked(is_cast(&blobby.character, id))?;
        }
        let nearest = nearest_size(blobby.size);
        for (size, item) in &self.sizes {
            item.set_checked(*size == nearest)?;
        }
        Ok(())
    }
}

fn is_cast(character: &Character, id: &str) -> bool {
    matches!(character, Character::Cast { id: chosen } if chosen == id)
}

/// The cast member a menu id names, if it names one.
pub fn cast_from_menu_id(id: &str) -> Option<String> {
    let wanted = id.strip_prefix(CAST_MENU_PREFIX)?;
    cast()
        .iter()
        .find(|member| member.id == wanted)
        .map(|member| member.id.clone())
}

/// Bottom-right of the primary monitor, clear of a dock or taskbar, for a blobby never placed yet.
fn default_position(app: &AppHandle, size: (f64, f64)) -> Option<(f64, f64)> {
    let monitor = app.primary_monitor().ok()??;
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size().to_logical::<f64>(scale);
    let origin = monitor.position().to_logical::<f64>(scale);
    Some((
        origin.x + monitor_size.width - size.0 - 48.0,
        origin.y + monitor_size.height - size.1 - 96.0,
    ))
}

/// Open blobby's window on the given server's page.
pub fn open(app: &AppHandle, server: &Url, blobby: &BlobbySettings) -> tauri::Result<WebviewWindow> {
    let page = server.join(PATH).map_err(|e| tauri::Error::Anyhow(e.into()))?;
    let version = app.package_info().version.to_string();
    let mut builder = crate::webview_profile::window(app, WINDOW, WebviewUrl::External(page))?
        .title("Blobby")
        .initialization_script(appearance::shell_script(&version, WINDOW))
        .inner_size(window_size(blobby.size).0, window_size(blobby.size).1)
        .transparent(true)
        .decorations(false)
        .shadow(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .focused(false)
        .accept_first_mouse(true);
    if let Some((x, y)) = blobby
        .position
        .map(|p| (p.x, p.y))
        .or_else(|| default_position(app, window_size(blobby.size)))
    {
        builder = builder.position(x, y);
    }
    let window = builder.build()?;
    // A file dropped on blobby starts a chat with it (#2305).
    let handle = app.clone();
    window.on_window_event(move |event| match event {
        WindowEvent::DragDrop(DragDropEvent::Enter { .. }) => {
            if let Err(e) = handle.emit_to(WINDOW, DROP_EVENT, "enter") {
                eprintln!("{e}");
            }
        }
        WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. }) => dropped::receive(&handle, paths.clone()),
        _ => {}
    });
    Ok(window)
}

/// Bring blobby's window in line with the settings: open, closed, or told who it is now.
pub fn sync(app: &AppHandle, server: Option<&Url>, blobby: &BlobbySettings) -> Result<(), String> {
    if blobby.enabled {
        if let Some(console) = app.get_webview_window(crate::WINDOW) {
            if crate::page_surface(&console.url().map_err(|e| e.to_string())?) == appearance::Surface::Setup {
                if let Some(window) = app.get_webview_window(WINDOW) {
                    window.hide().map_err(|e| e.to_string())?;
                }
                return Ok(());
            }
        }
    }
    match (app.get_webview_window(WINDOW), blobby.enabled, server) {
        (Some(window), false, _) => window.close().map_err(|e| e.to_string()),
        (Some(window), true, _) => {
            resize(&window, blobby.size)?;
            window.show().map_err(|e| e.to_string())?;
            app.emit_to(WINDOW, SETTINGS_EVENT, blobby).map_err(|e| e.to_string())
        }
        (None, true, Some(server)) => open(app, server, blobby).map(|_| ()).map_err(|e| e.to_string()),
        (None, _, _) => Ok(()),
    }
}

/// Grow or shrink blobby's window to a scale, keeping its feet where they were:
/// a creature standing on the dock should not float up off it when it shrinks.
pub fn resize(window: &WebviewWindow, scale: f64) -> Result<(), String> {
    let factor = window.scale_factor().map_err(|e| e.to_string())?;
    let old = window
        .outer_size()
        .map_err(|e| e.to_string())?
        .to_logical::<f64>(factor);
    let (width, height) = window_size(scale);
    if (old.width - width).abs() < 0.5 && (old.height - height).abs() < 0.5 {
        return Ok(());
    }
    let at = window
        .outer_position()
        .map_err(|e| e.to_string())?
        .to_logical::<f64>(factor);
    window
        .set_size(tauri::LogicalSize::new(width, height))
        .map_err(|e| e.to_string())?;
    window
        .set_position(tauri::LogicalPosition::new(
            at.x + (old.width - width) / 2.0,
            at.y + old.height - height,
        ))
        .map_err(|e| e.to_string())
}

/// Something blobby should say, from the shell rather than from its page.
pub fn say(app: &AppHandle, line: &str) {
    if let Err(e) = app.emit_to(WINDOW, SAY_EVENT, line) {
        eprintln!("blobby: {e}");
    }
}

#[cfg(test)]
mod tests {
    use super::{cast, cast_from_menu_id, validate, BlobbySettings, Character, Chatter, CAST_MENU_PREFIX};

    #[test]
    fn the_cast_file_parses_and_names_six_distinct_creatures() {
        let ids: std::collections::HashSet<_> = cast().iter().map(|m| m.id.as_str()).collect();
        assert_eq!(ids.len(), cast().len());
        assert!(cast().len() >= 6);
    }

    #[test]
    fn every_cast_member_has_a_menu_entry_that_resolves_back_to_it() {
        for member in cast() {
            assert_eq!(
                cast_from_menu_id(&format!("{CAST_MENU_PREFIX}{}", member.id)).as_deref(),
                Some(member.id.as_str())
            );
        }
        assert_eq!(cast_from_menu_id("show-blobby"), None);
        assert_eq!(cast_from_menu_id(&format!("{CAST_MENU_PREFIX}nobody")), None);
    }

    #[test]
    fn a_configuration_from_before_blobby_gets_the_first_of_the_cast_shown() {
        let blobby: BlobbySettings = serde_json::from_str("{}").unwrap();
        assert!(blobby.enabled && blobby.activity && blobby.roams);
        assert_eq!(blobby.chatter, Chatter::Normal);
        assert_eq!(
            blobby.character,
            Character::Cast {
                id: cast()[0].id.clone()
            }
        );
    }

    #[test]
    fn the_menu_ticks_the_size_nearest_a_pinch_and_names_each_one() {
        assert_eq!(super::nearest_size(0.8), 0.75);
        assert_eq!(super::nearest_size(1.1), 1.0);
        assert_eq!(super::nearest_size(1.6), 1.35);
        for (id, _, size) in super::SIZES {
            assert_eq!(super::size_from_menu_id(id), Some(size));
        }
        assert_eq!(super::size_from_menu_id("show-blobby"), None);
    }

    #[test]
    fn its_size_stays_in_range_and_a_nonsense_one_is_the_natural_one() {
        assert_eq!(super::clamp_scale(0.1), super::SCALE_RANGE.0);
        assert_eq!(super::clamp_scale(9.0), super::SCALE_RANGE.1);
        assert_eq!(super::clamp_scale(f64::NAN), 1.0);
        assert_eq!(super::window_size(1.0), super::SIZE);
        let blobby: BlobbySettings = serde_json::from_str("{}").unwrap();
        assert_eq!(blobby.size, 1.0);
    }

    #[test]
    fn a_character_round_trips_in_the_shape_the_console_sends() {
        let raw = r#"{"kind":"agent","agent_id":"a1","slug":"support","name":"Support","color_slot":3}"#;
        let character: Character = serde_json::from_str(raw).unwrap();
        assert_eq!(serde_json::to_string(&character).unwrap(), raw);
        assert!(validate(&character).is_ok());
    }

    #[test]
    fn a_character_out_of_bounds_is_refused() {
        assert!(validate(&Character::Cast { id: "nobody".into() }).is_err());
        assert!(validate(&Character::Custom {
            seed: " ".into(),
            color_slot: None
        })
        .is_err());
        assert!(validate(&Character::Custom {
            seed: "x".repeat(65),
            color_slot: None
        })
        .is_err());
        assert!(validate(&Character::Custom {
            seed: "kacper".into(),
            color_slot: Some(11)
        })
        .is_err());
        assert!(validate(&Character::Agent {
            agent_id: "a1".into(),
            slug: "s".into(),
            name: String::new(),
            color_slot: None
        })
        .is_err());
        assert!(validate(&Character::Custom {
            seed: "kacper".into(),
            color_slot: Some(10)
        })
        .is_ok());
    }
}
