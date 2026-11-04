//! The person's own screen, for their agent's computer use (#2305).
//!
//! **Asked first, stoppable always.** The first screen operation of a session
//! asks in a native dialog whether the agent may see and control this screen;
//! nothing is captured before the person says yes. While a run holds the screen
//! an outline frames it, and a global shortcut takes it back at once: the next
//! operation is refused, in a sentence the model reads, until the person allows
//! it again.
//!
//! The operating system asks too. macOS shows a screenshot of the desktop alone
//! until AgenticOS has Screen Recording, and drops input until it has
//! Accessibility; both are granted in System Settings, which the refusal names.

use std::io::Cursor;
use std::str::FromStr;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use base64::Engine;
use enigo::{Axis, Button, Coordinate, Direction, Enigo, Key, Keyboard, Mouse, Settings};
use serde::Deserialize;
use serde_json::{Map, Value};
#[cfg(target_os = "macos")]
use tauri::Emitter;
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};

/// How long one "allow" lasts; past it the person is asked again.
const ALLOWED_FOR: Duration = Duration::from_secs(60 * 60);

/// The shortcut that takes the screen back from the agent.
const STOP: &str = "CmdOrCtrl+Alt+Escape";

const OVERLAY: &str = "screen-overlay";

/// Whether, and until when, the person allowed their agent this screen.
#[derive(Default)]
pub struct ScreenState(Mutex<Option<Instant>>);

pub(crate) fn allowed(app: &AppHandle) -> bool {
    let state = app.state::<ScreenState>();
    let guard = state.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    guard.is_some_and(|until| Instant::now() < until)
}

fn set_allowed(app: &AppHandle, until: Option<Instant>) {
    let state = app.state::<ScreenState>();
    *state.0.lock().unwrap_or_else(|poisoned| poisoned.into_inner()) = until;
}

async fn ask(app: &AppHandle) -> bool {
    let (answered, answer) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(format!(
            "Your agent wants to see this screen and use the mouse and keyboard. \
             An outline shows while it does; press {} to stop it at any time.",
            STOP.replace("CmdOrCtrl", if cfg!(target_os = "macos") { "⌘" } else { "Ctrl" })
        ))
        .title("Let your agent use this screen?")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Allow for an hour".into(),
            "Don't allow".into(),
        ))
        .show(move |allowed| {
            let _ = answered.send(allowed);
        });
    answer.await.unwrap_or(false)
}

/// Take the screen back: refuse what follows, drop the outline and the shortcut.
pub(crate) fn stop(app: &AppHandle) {
    set_allowed(app, None);
    release(app);
}

fn hold(app: &AppHandle) {
    if app.get_webview_window(OVERLAY).is_none() {
        let built = WebviewWindowBuilder::new(app, OVERLAY, WebviewUrl::App("screen-overlay.html".into()))
            .title("AgenticOS is using this screen")
            .transparent(true)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .focused(false)
            .maximized(true)
            .shadow(false)
            .build();
        match built {
            Ok(window) => {
                let _ = window.set_ignore_cursor_events(true);
            }
            Err(e) => eprintln!("screen outline: {e}"),
        }
    }
    let shortcuts = app.global_shortcut();
    if let Ok(shortcut) = Shortcut::from_str(STOP) {
        if !shortcuts.is_registered(shortcut) {
            let registered = shortcuts.on_shortcut(shortcut, |app, _shortcut, event| {
                if event.state == ShortcutState::Pressed {
                    stop(app);
                }
            });
            if let Err(e) = registered {
                eprintln!("screen stop shortcut: {e}");
            }
        }
    }
}

fn release(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(OVERLAY) {
        let _ = window.close();
    }
    let _ = app.global_shortcut().unregister(STOP);
}

/// One `screen.*` operation; a refusal carries its kind as the device frames do.
pub async fn run(
    app: &AppHandle,
    op: &str,
    args: &Map<String, Value>,
) -> Result<Map<String, Value>, (String, &'static str)> {
    if op == "screen.release" {
        release(app);
        return Ok(Map::new());
    }
    #[cfg(target_os = "macos")]
    {
        let status = crate::onboarding_permissions::onboarding_permissions();
        let missing = if op == "screen.capture" && !status.screen_capture {
            Some("screen_capture")
        } else if op == "screen.act" && !status.accessibility {
            Some("accessibility")
        } else {
            None
        };
        if let Some(permission) = missing {
            let _ = app.emit("desktop:repair-needed", permission);
            return Err((format!("macOS permission is missing.{PERMISSIONS}"), "denied"));
        }
    }
    if !allowed(app) {
        if !ask(app).await {
            return Err(("The person did not allow you to use their screen.".into(), "denied"));
        }
        set_allowed(app, Some(Instant::now() + ALLOWED_FOR));
    }
    hold(app);
    match op {
        "screen.capture" => tauri::async_runtime::spawn_blocking(capture)
            .await
            .map_err(|e| (e.to_string(), "io"))?,
        "screen.act" => {
            let action: Action = serde_json::from_value(args.get("action").cloned().unwrap_or(Value::Null))
                .map_err(|e| (format!("This app does not know that action: {e}"), "denied"))?;
            tauri::async_runtime::spawn_blocking(move || act(action))
                .await
                .map_err(|e| (e.to_string(), "io"))?
                .map(|()| Map::new())
        }
        other => Err((format!("This app does not do {other} yet. Update AgenticOS."), "denied")),
    }
}

const PERMISSIONS: &str = if cfg!(target_os = "macos") {
    " Allow AgenticOS under System Settings → Privacy & Security → Screen Recording and Accessibility."
} else {
    ""
};

fn capture() -> Result<Map<String, Value>, (String, &'static str)> {
    let failed = |e: xcap::XCapError| (format!("The screen could not be captured: {e}.{PERMISSIONS}"), "io");
    let monitors = xcap::Monitor::all().map_err(failed)?;
    let monitor = monitors
        .iter()
        .find(|monitor| monitor.is_primary().unwrap_or(false))
        .or(monitors.first())
        .ok_or_else(|| ("This computer has no screen to capture.".to_owned(), "io"))?;
    let image = monitor.capture_image().map_err(failed)?;
    // Keep pointer coordinates native while bounding the transmitted picture.
    let width = monitor.width().unwrap_or(image.width());
    let height = monitor.height().unwrap_or(image.height());
    let png = preview_bytes(image).map_err(|e| (e, "io"))?;
    let mut value = Map::new();
    value.insert(
        "data".into(),
        base64::engine::general_purpose::STANDARD.encode(png).into(),
    );
    // The space the pointer moves in: points on a Retina Mac, pixels elsewhere.
    value.insert("width".into(), width.into());
    value.insert("height".into(), height.into());
    value.insert("platform".into(), crate::device::PLATFORM.into());
    Ok(value)
}

/// Bound a Retina/4K capture before PNG/base64 encoding, below the hub's frame limit.
fn preview_bytes(image: image::RgbaImage) -> Result<Vec<u8>, String> {
    let width = image.width().min(1600);
    let height = image.height().min(1000);
    let image = image::DynamicImage::ImageRgba8(image).thumbnail(width, height);
    let mut png = Vec::new();
    image
        .write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
        .map_err(|e| format!("The screenshot could not be encoded: {e}"))?;
    Ok(png)
}

/// One action as the server sends it - `_actions.py`'s models, already in native coordinates.
#[derive(Deserialize)]
#[serde(tag = "action", rename_all = "snake_case")]
enum Action {
    Click {
        x: i32,
        y: i32,
        #[serde(default)]
        button: MouseButton,
        #[serde(default = "one")]
        count: u32,
    },
    Move {
        x: i32,
        y: i32,
    },
    Drag {
        x: i32,
        y: i32,
        to_x: i32,
        to_y: i32,
    },
    Scroll {
        x: i32,
        y: i32,
        direction: ScrollDirection,
        #[serde(default = "three")]
        amount: i32,
    },
    Type {
        text: String,
    },
    Key {
        keys: String,
    },
}

fn one() -> u32 {
    1
}

fn three() -> i32 {
    3
}

#[derive(Deserialize, Default, Clone, Copy)]
#[serde(rename_all = "snake_case")]
enum MouseButton {
    #[default]
    Left,
    Right,
    Middle,
}

#[derive(Deserialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
enum ScrollDirection {
    Up,
    Down,
    Left,
    Right,
}

fn act(action: Action) -> Result<(), (String, &'static str)> {
    let refused = |e: enigo::InputError| (format!("The action could not be carried out: {e}.{PERMISSIONS}"), "io");
    let mut enigo = Enigo::new(&Settings::default())
        .map_err(|e| (format!("This screen cannot be controlled: {e}.{PERMISSIONS}"), "io"))?;
    match action {
        Action::Click { x, y, button, count } => {
            enigo.move_mouse(x, y, Coordinate::Abs).map_err(refused)?;
            let button = match button {
                MouseButton::Left => Button::Left,
                MouseButton::Right => Button::Right,
                MouseButton::Middle => Button::Middle,
            };
            for _ in 0..count {
                enigo.button(button, Direction::Click).map_err(refused)?;
            }
        }
        Action::Move { x, y } => enigo.move_mouse(x, y, Coordinate::Abs).map_err(refused)?,
        Action::Drag { x, y, to_x, to_y } => {
            enigo.move_mouse(x, y, Coordinate::Abs).map_err(refused)?;
            enigo.button(Button::Left, Direction::Press).map_err(refused)?;
            std::thread::sleep(Duration::from_millis(50));
            enigo.move_mouse(to_x, to_y, Coordinate::Abs).map_err(refused)?;
            enigo.button(Button::Left, Direction::Release).map_err(refused)?;
        }
        Action::Scroll {
            x,
            y,
            direction,
            amount,
        } => {
            enigo.move_mouse(x, y, Coordinate::Abs).map_err(refused)?;
            let (length, axis) = match direction {
                ScrollDirection::Up => (-amount, Axis::Vertical),
                ScrollDirection::Down => (amount, Axis::Vertical),
                ScrollDirection::Left => (-amount, Axis::Horizontal),
                ScrollDirection::Right => (amount, Axis::Horizontal),
            };
            enigo.scroll(length, axis).map_err(refused)?;
        }
        Action::Type { text } => enigo.text(&text).map_err(refused)?,
        Action::Key { keys } => {
            let chord = chord(&keys).map_err(|e| (e, "denied"))?;
            let (last, modifiers) = chord
                .split_last()
                .ok_or_else(|| (format!("{keys:?} names no key."), "denied"))?;
            for key in modifiers {
                enigo.key(*key, Direction::Press).map_err(refused)?;
            }
            let pressed = enigo.key(*last, Direction::Click).map_err(refused);
            for key in modifiers.iter().rev() {
                let _ = enigo.key(*key, Direction::Release);
            }
            pressed?;
        }
    }
    Ok(())
}

/// A chord as the model spells it - `ctrl+shift+t`, `enter`, `cmd+c` - as keys.
fn chord(keys: &str) -> Result<Vec<Key>, String> {
    keys.split('+')
        .map(str::trim)
        .filter(|part| !part.is_empty())
        .map(|part| named(part).ok_or_else(|| format!("{part:?} is not a key this app knows.")))
        .collect()
}

fn named(part: &str) -> Option<Key> {
    let lower = part.to_lowercase();
    Some(match lower.as_str() {
        "enter" | "return" => Key::Return,
        "esc" | "escape" => Key::Escape,
        "tab" => Key::Tab,
        "space" => Key::Space,
        "backspace" => Key::Backspace,
        "delete" | "del" => Key::Delete,
        "home" => Key::Home,
        "end" => Key::End,
        "pageup" | "page_up" => Key::PageUp,
        "pagedown" | "page_down" => Key::PageDown,
        "up" => Key::UpArrow,
        "down" => Key::DownArrow,
        "left" => Key::LeftArrow,
        "right" => Key::RightArrow,
        "ctrl" | "control" => Key::Control,
        "alt" | "option" => Key::Alt,
        "shift" => Key::Shift,
        "cmd" | "command" | "super" | "meta" | "win" => Key::Meta,
        _ => {
            if let Some(number) = lower.strip_prefix('f').and_then(|n| n.parse::<u8>().ok()) {
                return function_key(number);
            }
            let mut chars = part.chars();
            match (chars.next(), chars.next()) {
                (Some(c), None) => Key::Unicode(c.to_ascii_lowercase()),
                _ => return None,
            }
        }
    })
}

fn function_key(number: u8) -> Option<Key> {
    Some(match number {
        1 => Key::F1,
        2 => Key::F2,
        3 => Key::F3,
        4 => Key::F4,
        5 => Key::F5,
        6 => Key::F6,
        7 => Key::F7,
        8 => Key::F8,
        9 => Key::F9,
        10 => Key::F10,
        11 => Key::F11,
        12 => Key::F12,
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn screen_previews_bound_pixels_without_enlarging_small_displays() {
        for (width, height, expected) in [(3200, 2000, (1600, 1000)), (800, 600, (800, 600))] {
            let bytes = preview_bytes(image::RgbaImage::new(width, height)).unwrap();
            let preview = image::load_from_memory(&bytes).unwrap();
            assert_eq!((preview.width(), preview.height()), expected);
            assert!(bytes.len() < 8 * 1024 * 1024);
        }
    }

    #[test]
    fn chords_are_read_as_the_model_writes_them() {
        assert_eq!(
            chord("ctrl+shift+t").unwrap(),
            vec![Key::Control, Key::Shift, Key::Unicode('t')]
        );
        assert_eq!(chord("Enter").unwrap(), vec![Key::Return]);
        assert_eq!(chord("cmd+F5").unwrap(), vec![Key::Meta, Key::F5]);
        assert!(chord("hyper+q").is_err());
    }

    #[test]
    fn actions_are_read_in_the_servers_shape() {
        let click: Action = serde_json::from_value(serde_json::json!({"action": "click", "x": 1, "y": 2})).unwrap();
        assert!(matches!(
            click,
            Action::Click {
                x: 1,
                y: 2,
                count: 1,
                ..
            }
        ));
        let scroll: Action = serde_json::from_value(
            serde_json::json!({"action": "scroll", "x": 0, "y": 0, "direction": "up", "amount": 2}),
        )
        .unwrap();
        assert!(matches!(scroll, Action::Scroll { amount: 2, .. }));
    }
}
