//! Quick ask: a floating glass panel over whatever you are doing, opened by a
//! global shortcut (`⌥Space` unless rebound).
//!
//! Like blobby, the panel is the shell's window and the console's page -
//! `/desktop/quick-ask` - so it asks with the console's session and streams the
//! answer over the console's own chat socket. It is built once, hidden, as soon
//! as a server is known: a panel that has to load a page on the keypress opens a
//! second late, and a second is the difference between a launcher and a window.
//!
//! On macOS it is an `NSPanel` that does not activate the app, as Spotlight's
//! is: it takes the keyboard while the app you were in stays the active one,
//! and the console window stays wherever it was.

use std::sync::atomic::{AtomicBool, Ordering};

use tauri::{AppHandle, Emitter, LogicalSize, Manager, PhysicalPosition, Url, WebviewUrl, WebviewWindow};

use crate::appearance::{self, Appearance, Surface};

pub const WINDOW: &str = "quick-ask";
pub const PATH: &str = "desktop/quick-ask";
pub const OPEN_EVENT: &str = "desktop:quick-ask";
/// Push to talk: `"start"` while the shortcut is held, `"stop"` when it is let go.
pub const DICTATE_EVENT: &str = "desktop:dictate";
const WIDTH: f64 = 680.0;
/// The panel with only its question row showing.
pub const MIN_HEIGHT: f64 = 64.0;
/// As tall as it grows for an answer; longer answers scroll inside it.
pub const MAX_HEIGHT: f64 = 560.0;
/// How far down the screen it sits, as Spotlight's does.
const FROM_TOP: f64 = 0.2;

/// Focus policy belongs to the native window, so page reloads retain the pin.
#[derive(Default)]
pub struct PanelState {
    pinned: AtomicBool,
    picking: AtomicBool,
}

impl PanelState {
    fn dismiss_on_blur(&self) -> bool {
        !self.pinned.load(Ordering::Relaxed) && !self.picking.load(Ordering::Relaxed)
    }
}

/// Build the panel hidden, ready for the shortcut.
pub fn prepare(app: &AppHandle, server: &Url, appearance: Appearance) -> tauri::Result<WebviewWindow> {
    let page = server.join(PATH).map_err(|e| tauri::Error::Anyhow(e.into()))?;
    let version = app.package_info().version.to_string();
    let mut builder = crate::webview_profile::window(app, WINDOW, WebviewUrl::External(page))?
        .title("Quick ask")
        .disable_drag_drop_handler()
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
    #[cfg(target_os = "macos")]
    {
        let ns_window = window.ns_window()? as usize;
        // SAFETY: the pointer is the live NSWindow of the window just built,
        // used on the main thread, where AppKit requires it.
        window.run_on_main_thread(move || unsafe { mac::make_panel(ns_window) })?;
    }
    // A pinned panel stays visible. File dialogs temporarily take focus without
    // dismissing the draft they belong to.
    let handle = window.clone();
    window.on_window_event(move |event| {
        if matches!(event, tauri::WindowEvent::Focused(false)) && handle.state::<PanelState>().dismiss_on_blur() {
            if let Err(e) = handle.hide() {
                eprintln!("quick ask: {e}");
            }
        }
    });
    Ok(window)
}

/// The panel, built now if the server came after start-up.
fn panel(app: &AppHandle, server: Option<&Url>, appearance: Appearance) -> Result<WebviewWindow, String> {
    match app.get_webview_window(WINDOW) {
        Some(window) => Ok(window),
        None => {
            let server = server.ok_or("No server yet - connect the console to one first.")?;
            prepare(app, server, appearance).map_err(|e| e.to_string())
        }
    }
}

/// The shortcut: show the panel where the cursor is, or put it away if it is up.
pub fn toggle(app: &AppHandle, server: Option<&Url>, appearance: Appearance) -> Result<(), String> {
    let window = panel(app, server, appearance)?;
    if window.is_visible().map_err(|e| e.to_string())? {
        return window.hide().map_err(|e| e.to_string());
    }
    open(app, &window)
}

/// Bring the panel up with what was in front a moment before it: read first,
/// since once the panel is up, the panel is what is in front.
fn open(app: &AppHandle, window: &WebviewWindow) -> Result<(), String> {
    let context = crate::context::capture(app);
    place(app, window)?;
    present(window)?;
    app.emit_to(WINDOW, OPEN_EVENT, context).map_err(|e| e.to_string())
}

/// Push to talk: held, the panel comes up - if it is not already - and records;
/// let go, it stops, and the words become its question.
pub fn dictate(app: &AppHandle, server: Option<&Url>, appearance: Appearance, held: bool) -> Result<(), String> {
    let window = panel(app, server, appearance)?;
    if held && !window.is_visible().map_err(|e| e.to_string())? {
        open(app, &window)?;
    }
    app.emit_to(WINDOW, DICTATE_EVENT, if held { "start" } else { "stop" })
        .map_err(|e| e.to_string())
}

/// Bring the panel up with the keyboard. On macOS without activating the app:
/// Tauri's `set_focus` would, and the console window would come forward with it.
#[cfg(target_os = "macos")]
fn present(window: &WebviewWindow) -> Result<(), String> {
    let ns_window = window.ns_window().map_err(|e| e.to_string())? as usize;
    // SAFETY: as in `prepare` - the window's live NSWindow, on the main thread.
    window
        .run_on_main_thread(move || unsafe { mac::present(ns_window) })
        .map_err(|e| e.to_string())
}

#[cfg(not(target_os = "macos"))]
fn present(window: &WebviewWindow) -> Result<(), String> {
    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())
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

#[cfg(target_os = "macos")]
mod mac {
    use std::sync::OnceLock;

    use objc2::runtime::{AnyClass, AnyObject, Bool, ClassBuilder, Sel};
    use objc2::{class, msg_send, sel};

    /// `NSWindowStyleMaskNonactivatingPanel`: key without making the app active.
    const NONACTIVATING_PANEL: usize = 1 << 7;
    /// `NSWindowCollectionBehaviorCanJoinAllSpaces | …FullScreenAuxiliary`: on
    /// every Space, and over an app in full screen.
    const EVERY_SPACE: usize = (1 << 0) | (1 << 8);

    /// An `NSPanel` that takes the keyboard, which a borderless one refuses,
    /// and never becomes the main window.
    fn panel_class() -> &'static AnyClass {
        static CLASS: OnceLock<&'static AnyClass> = OnceLock::new();
        CLASS.get_or_init(|| {
            extern "C-unwind" fn yes(_: &AnyObject, _: Sel) -> Bool {
                Bool::YES
            }
            extern "C-unwind" fn no(_: &AnyObject, _: Sel) -> Bool {
                Bool::NO
            }
            let mut builder = ClassBuilder::new(c"AgenticOSQuickAskPanel", class!(NSPanel))
                .expect("the quick ask panel class is declared once");
            // SAFETY: both selectors take no arguments and return BOOL.
            unsafe {
                builder.add_method(sel!(canBecomeKeyWindow), yes as extern "C-unwind" fn(_, _) -> _);
                builder.add_method(sel!(canBecomeMainWindow), no as extern "C-unwind" fn(_, _) -> _);
            }
            builder.register()
        })
    }

    /// Turn the window into the panel. The window's delegate - and with it
    /// Tauri's focus and move events - is the object's, and stays.
    ///
    /// # Safety
    /// `ns_window` is a live NSWindow, and this runs on the main thread.
    pub unsafe fn make_panel(ns_window: usize) {
        let window = &*(ns_window as *const AnyObject);
        AnyObject::set_class(window, panel_class());
        let mask: usize = msg_send![window, styleMask];
        let _: () = msg_send![window, setStyleMask: mask | NONACTIVATING_PANEL];
        let _: () = msg_send![window, setFloatingPanel: Bool::YES];
        let _: () = msg_send![window, setHidesOnDeactivate: Bool::NO];
        let _: () = msg_send![window, setCollectionBehavior: EVERY_SPACE];
    }

    /// Show it over everything, with the keyboard, the app left as it was.
    ///
    /// # Safety
    /// As `make_panel`.
    pub unsafe fn present(ns_window: usize) {
        let window = &*(ns_window as *const AnyObject);
        let _: () = msg_send![window, orderFrontRegardless];
        let _: () = msg_send![window, makeKeyWindow];
    }
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

/// Only this panel can change its focus policy.
fn panel_state(window: &WebviewWindow) -> Result<tauri::State<'_, PanelState>, String> {
    if window.label() != WINDOW {
        return Err("Quick Ask window required".into());
    }
    Ok(window.state::<PanelState>())
}

#[tauri::command]
pub fn quick_ask_pinned(window: WebviewWindow) -> Result<bool, String> {
    Ok(panel_state(&window)?.pinned.load(Ordering::Relaxed))
}

#[tauri::command]
pub fn set_quick_ask_pinned(window: WebviewWindow, pinned: bool) -> Result<(), String> {
    panel_state(&window)?.pinned.store(pinned, Ordering::Relaxed);
    Ok(())
}

/// The native file chooser may temporarily take focus from an unpinned panel.
#[tauri::command]
pub fn set_quick_ask_picker_open(window: WebviewWindow, open: bool) -> Result<(), String> {
    panel_state(&window)?.picking.store(open, Ordering::Relaxed);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{clamp_height, PanelState, MAX_HEIGHT, MIN_HEIGHT};
    use std::sync::atomic::Ordering;

    #[test]
    fn pin_and_file_chooser_keep_the_panel_visible_until_explicitly_dismissed() {
        let state = PanelState::default();
        assert!(state.dismiss_on_blur());
        state.pinned.store(true, Ordering::Relaxed);
        assert!(!state.dismiss_on_blur());
        state.picking.store(true, Ordering::Relaxed);
        state.pinned.store(false, Ordering::Relaxed);
        assert!(!state.dismiss_on_blur());
        state.picking.store(false, Ordering::Relaxed);
        assert!(state.dismiss_on_blur());
    }

    #[test]
    fn the_panel_never_shrinks_past_its_question_or_grows_past_its_ceiling() {
        assert_eq!(clamp_height(10.0), MIN_HEIGHT);
        assert_eq!(clamp_height(300.0), 300.0);
        assert_eq!(clamp_height(5000.0), MAX_HEIGHT);
        assert_eq!(clamp_height(f64::NAN), MIN_HEIGHT);
    }
}
