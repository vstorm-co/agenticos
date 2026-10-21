//! How the shell's windows look: the console's style and light/dark mode, and the
//! native material behind a glass window.
//!
//! The console owns the choice - it is a setting on its Appearance page, kept in
//! the browser like the theme always was - and tells the shell whenever it
//! changes. The shell keeps a copy for one reason: the next launch builds the
//! window before the page has loaded, and a glass window that starts opaque and
//! turns translucent half a second later is the flash a native app never shows.

use serde::{Deserialize, Serialize};
use tauri::utils::config::WindowEffectsConfig;
use tauri::window::{Effect, EffectState, EffectsBuilder};
use tauri::{Theme, WebviewWindow};

/// The console's style. Each is a set of colour tokens in the console's CSS; only
/// `Glass` also asks something of the window.
#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Default, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Look {
    #[default]
    Standard,
    Glass,
    Graphite,
    Midnight,
    Paper,
}

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Default, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    Light,
    Dark,
    #[default]
    System,
}

#[derive(Serialize, Deserialize, Clone, Copy, PartialEq, Eq, Default, Debug)]
pub struct Appearance {
    #[serde(default)]
    pub look: Look,
    #[serde(default)]
    pub mode: Mode,
}

/// Which surface a material is for. The console wants the sidebar material, the
/// one Finder's and Mail's columns use; a floating panel wants the heavier HUD.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Surface {
    Console,
    Panel,
}

/// Whether this platform draws a real material behind a transparent window.
///
/// Linux has no compositor-independent one, so a glass console there is the
/// console's own CSS approximation over an opaque window - a transparent window
/// would show the desktop through it unblurred.
pub const VIBRANCY: bool = cfg!(any(target_os = "macos", target_os = "windows"));

/// The window's own theme, which decides whether the material is drawn light or dark.
pub fn theme(mode: Mode) -> Option<Theme> {
    match mode {
        Mode::Light => Some(Theme::Light),
        Mode::Dark => Some(Theme::Dark),
        Mode::System => None,
    }
}

/// The material behind a window, or `None` for an opaque one.
///
/// A panel is always glass: quick ask floats over whatever the person was doing,
/// and an opaque slab there reads as a dialog box rather than as part of the
/// system. The console is glass only when that is the chosen look.
pub fn effects(surface: Surface, look: Look) -> Option<WindowEffectsConfig> {
    if !VIBRANCY || (surface == Surface::Console && look != Look::Glass) {
        return None;
    }
    let effect = match (surface, cfg!(target_os = "macos")) {
        (Surface::Console, true) => Effect::Sidebar,
        (Surface::Panel, true) => Effect::HudWindow,
        (Surface::Console, false) => Effect::Mica,
        (Surface::Panel, false) => Effect::Acrylic,
    };
    // An inactive window keeps its material: macOS greys an inactive sidebar
    // out by default, and a console in the background of a second monitor is
    // still being read.
    let builder = EffectsBuilder::new().effect(effect).state(EffectState::Active);
    Some(match surface {
        Surface::Panel => builder.radius(PANEL_RADIUS).build(),
        Surface::Console => builder.build(),
    })
}

/// The corner radius of a floating panel, matching Spotlight's.
pub const PANEL_RADIUS: f64 = 16.0;

/// Put a window in the given appearance: its theme, then its material.
pub fn apply(window: &WebviewWindow, surface: Surface, appearance: Appearance) -> tauri::Result<()> {
    window.set_theme(theme(appearance.mode))?;
    window.set_effects(effects(surface, appearance.look))
}

/// What a page needs to know about the shell before its first paint.
///
/// Set as `window.__AGENTICOS_SHELL__` by an initialization script, which runs
/// before any script of the page: the console reads it in its own pre-paint
/// script to lay itself out around the traffic lights and to make its
/// background transparent over a material, so neither arrives a frame late.
#[derive(Serialize)]
pub struct ShellInfo<'a> {
    pub platform: &'static str,
    pub version: &'a str,
    pub window: &'a str,
    pub vibrancy: bool,
}

pub fn platform() -> &'static str {
    if cfg!(target_os = "macos") {
        "macos"
    } else if cfg!(target_os = "windows") {
        "windows"
    } else {
        "linux"
    }
}

/// The initialization script announcing the shell to a page in the named window.
pub fn shell_script(version: &str, window: &str) -> String {
    let info = ShellInfo {
        platform: platform(),
        version,
        window,
        vibrancy: VIBRANCY,
    };
    let json = serde_json::to_string(&info).expect("a struct of strings and a bool serializes");
    format!("Object.defineProperty(window, \"__AGENTICOS_SHELL__\", {{ value: Object.freeze({json}) }});")
}

#[cfg(test)]
mod tests {
    use super::{effects, shell_script, Appearance, Look, Mode, Surface, VIBRANCY};

    #[test]
    fn only_a_glass_console_asks_for_a_material() {
        for look in [Look::Standard, Look::Graphite, Look::Midnight, Look::Paper] {
            assert!(effects(Surface::Console, look).is_none(), "{look:?}");
        }
        assert_eq!(effects(Surface::Console, Look::Glass).is_some(), VIBRANCY);
    }

    #[test]
    fn a_panel_is_glass_whatever_the_console_wears() {
        assert_eq!(effects(Surface::Panel, Look::Standard).is_some(), VIBRANCY);
    }

    #[test]
    fn an_appearance_saved_before_looks_existed_is_the_standard_system_one() {
        let appearance: Appearance = serde_json::from_str("{}").unwrap();
        assert_eq!(appearance.look, Look::Standard);
        assert_eq!(appearance.mode, Mode::System);
    }

    #[test]
    fn looks_and_modes_are_spelled_the_way_the_console_spells_them() {
        let raw = serde_json::to_string(&Appearance {
            look: Look::Midnight,
            mode: Mode::Dark,
        })
        .unwrap();
        assert_eq!(raw, r#"{"look":"midnight","mode":"dark"}"#);
    }

    #[test]
    fn the_shell_script_defines_a_frozen_global_naming_the_window() {
        let script = shell_script("1.2.3", "blobby");
        assert!(script.contains("__AGENTICOS_SHELL__"));
        assert!(script.contains(r#""window":"blobby""#));
        assert!(script.contains(r#""version":"1.2.3""#));
        assert!(script.contains("Object.freeze"));
    }
}
