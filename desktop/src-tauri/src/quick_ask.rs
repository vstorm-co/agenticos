//! Quick ask: a floating glass panel over whatever you are doing, opened by a
//! global shortcut (`⌥Space` unless rebound).
//!
//! Like blobby, the panel is the shell's window and the console's page -
//! `/desktop/quick-ask` - so it asks with the console's session and streams the
//! answer over the console's own chat socket. It is built once, hidden, as soon
//! as a server is known: a panel that has to load a page on the keypress opens a
//! second late, and a second is the difference between a launcher and a window.

use tauri::{
    AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
};

use crate::appearance::{self, Appearance, Surface};

pub const WINDOW: &str = "quick-ask";
pub const PATH: &str = "desktop/quick-ask";
pub const OPEN_EVENT: &str = "desktop:quick-ask";
const WIDTH: f64 = 680.0;
/// The panel with only its question row showing.
pub const MIN_HEIGHT: f64 = 64.0;
/// As tall as it grows for an answer; longer answers scroll inside it.
pub const MAX_HEIGHT: f64 = 560.0;
/// How far down the screen it sits, as Spotlight's does.
const FROM_TOP: f64 = 0.2;

/// Build the panel hidden, ready for the shortcut.
pub fn prepare(app: &AppHandle, server: &Url, appearance: Appearance) -> tauri::Result<WebviewWindow> {
    let page = server.join(PATH).map_err(|e| tauri::Error::Anyhow(e.into()))?;
    let version = app.package_info().version.to_string();
    let mut builder = WebviewWindowBuilder::new(app, WINDOW, WebviewUrl::External(page))
        .title("Quick ask")
        .initialization_script(appearance::shell_script(&version, WINDOW))
        .inner_size(WIDTH, MIN_HEIGHT)
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .resizable(false)
        .maximizable(false)
        .minimizable(false)
        .visible(false)
        .theme(appearance::theme(appearance.mode));
    if let Some(effects) = appearance::effects(Surface::Panel, appearance.look) {
        builder = builder.effects(effects);
    }
    let window = builder.build()?;
    // A panel that loses focus has been dismissed: clicking elsewhere is how
    // every launcher on every platform is put away.
    let handle = window.clone();
    window.on_window_event(move |event| {
        if let tauri::WindowEvent::Focused(false) = event {
            if let Err(e) = handle.hide() {
                eprintln!("quick ask: {e}");
            }
        }
    });
    Ok(window)
}

/// The shortcut: show the panel where the cursor is, or put it away if it is up.
pub fn toggle(app: &AppHandle, server: Option<&Url>, appearance: Appearance) -> Result<(), String> {
    let window = match app.get_webview_window(WINDOW) {
        Some(window) => window,
        None => {
            let server = server.ok_or("No server yet - connect the console to one first.")?;
            prepare(app, server, appearance).map_err(|e| e.to_string())?
        }
    };
    if window.is_visible().map_err(|e| e.to_string())? {
        return window.hide().map_err(|e| e.to_string());
    }
    place(app, &window)?;
    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;
    app.emit_to(WINDOW, OPEN_EVENT, ()).map_err(|e| e.to_string())
}

/// Centre it on the monitor the cursor is on, a fifth of the way down.
fn place(app: &AppHandle, window: &WebviewWindow) -> Result<(), String> {
    let cursor = app.cursor_position().map_err(|e| e.to_string())?;
    let monitor = app
        .monitor_from_point(cursor.x, cursor.y)
        .map_err(|e| e.to_string())?
        .or(app.primary_monitor().map_err(|e| e.to_string())?)
        .ok_or("No monitor to show quick ask on.")?;
    let outer = window.outer_size().map_err(|e| e.to_string())?;
    let (origin, size) = (monitor.position(), monitor.size());
    let x = origin.x + (size.width as i32 - outer.width as i32) / 2;
    let y = origin.y + (f64::from(size.height) * FROM_TOP) as i32;
    window
        .set_position(PhysicalPosition::new(x, y))
        .map_err(|e| e.to_string())
}

/// The height the page asks for, kept between the question row and the ceiling.
pub fn clamp_height(height: f64) -> f64 {
    if height.is_nan() {
        return MIN_HEIGHT;
    }
    height.clamp(MIN_HEIGHT, MAX_HEIGHT)
}

#[tauri::command]
pub fn resize_quick_ask(window: WebviewWindow, height: f64) -> Result<(), String> {
    window
        .set_size(LogicalSize::new(WIDTH, clamp_height(height)))
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn hide_quick_ask(window: WebviewWindow) -> Result<(), String> {
    window.hide().map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::{clamp_height, MAX_HEIGHT, MIN_HEIGHT};

    #[test]
    fn the_panel_never_shrinks_past_its_question_or_grows_past_its_ceiling() {
        assert_eq!(clamp_height(10.0), MIN_HEIGHT);
        assert_eq!(clamp_height(300.0), 300.0);
        assert_eq!(clamp_height(5000.0), MAX_HEIGHT);
        assert_eq!(clamp_height(f64::NAN), MIN_HEIGHT);
    }
}
