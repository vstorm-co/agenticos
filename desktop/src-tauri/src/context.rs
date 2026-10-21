//! What you were looking at when you opened quick ask (#2305): the app in
//! front, its window, the text selected in it, the clipboard, and the files
//! selected in Finder.
//!
//! Read before the panel comes up - after, the panel is what is in front - and
//! handed to the panel as chips the person can see and take off. The words
//! travel with the open event; a file's bytes only through
//! `take_context_files`, and only the files this capture found: the panel is a
//! page of a remote server, and must not be able to ask for any other path.
//!
//! The selection and the window title need the Accessibility permission; the
//! panel says so rather than the app asking out of nowhere. Finder's selection
//! asks Finder through Apple Events, which macOS confirms once.

use std::path::PathBuf;
use std::sync::Mutex;

use base64::Engine;
use serde::Serialize;
use tauri::{AppHandle, Manager};

/// A file larger than this is named, not read.
const MAX_FILE_BYTES: u64 = 20 * 1024 * 1024;
/// Finder's selection, at most: a chat message is not a file transfer.
const MAX_FILES: usize = 5;
/// The selection and the clipboard, cut here: a page of text is context, a
/// whole document pasted from the clipboard is not.
const MAX_TEXT_CHARS: usize = 8_000;

/// What the panel shows as chips.
#[derive(Serialize, Default, Clone, Debug, PartialEq)]
pub struct ActiveContext {
    /// The app in front, by name.
    pub app: Option<String>,
    /// Its focused window's title.
    pub window: Option<String>,
    pub selection: Option<String>,
    pub clipboard: Option<String>,
    /// Finder's selection, by name; the bytes come through `take_context_files`.
    pub files: Vec<String>,
    /// Whether this app may read other apps' windows - without it there is no
    /// selection and no window title, and the panel offers to fix that.
    pub accessibility: bool,
}

/// The files the last capture found, for `take_context_files` to read.
#[derive(Default)]
pub struct CapturedFiles(Mutex<Vec<PathBuf>>);

fn cut(text: String) -> Option<String> {
    let text = text.trim();
    if text.is_empty() {
        return None;
    }
    Some(text.chars().take(MAX_TEXT_CHARS).collect())
}

/// Read what is in front, and remember the files it found.
pub fn capture(app: &AppHandle) -> ActiveContext {
    let (context, files) = platform::capture();
    if let Ok(mut held) = app.state::<CapturedFiles>().0.lock() {
        *held = files;
    }
    context
}

/// One file of the captured selection, for the panel to attach.
#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ContextFile {
    pub name: String,
    /// The bytes, base64.
    pub data: String,
}

/// The captured Finder selection's files, read now and forgotten after: what
/// was selected when the panel opened, and nothing else.
#[tauri::command]
pub fn take_context_files(app: AppHandle) -> Result<Vec<ContextFile>, String> {
    let paths = app
        .state::<CapturedFiles>()
        .0
        .lock()
        .map(|mut held| std::mem::take(&mut *held))
        .map_err(|e| e.to_string())?;
    paths.iter().map(|path| read(path)).collect()
}

fn read(path: &std::path::Path) -> Result<ContextFile, String> {
    let name = path
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let size = std::fs::metadata(path).map_err(|e| format!("{name}: {e}"))?.len();
    if size > MAX_FILE_BYTES {
        return Err(format!("{name} is larger than 20 MB."));
    }
    let bytes = std::fs::read(path).map_err(|e| format!("{name}: {e}"))?;
    Ok(ContextFile {
        name,
        data: base64::engine::general_purpose::STANDARD.encode(bytes),
    })
}

/// Where to grant the Accessibility permission.
#[tauri::command]
pub fn open_accessibility_settings(app: AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    app.opener()
        .open_url(
            "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
            None::<&str>,
        )
        .map_err(|e| e.to_string())
}

#[cfg(target_os = "macos")]
mod platform {
    use std::ffi::{c_void, CStr};
    use std::path::PathBuf;
    use std::process::Command;

    use objc2::runtime::AnyObject;
    use objc2::{class, msg_send};

    use super::{cut, ActiveContext, MAX_FILES};

    type CFTypeRef = *const c_void;

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        fn AXIsProcessTrusted() -> bool;
        fn AXUIElementCreateApplication(pid: i32) -> CFTypeRef;
        fn AXUIElementCopyAttributeValue(element: CFTypeRef, attribute: CFTypeRef, value: *mut CFTypeRef) -> i32;
    }

    #[link(name = "CoreFoundation", kind = "framework")]
    extern "C" {
        fn CFRelease(value: CFTypeRef);
    }

    /// An NSString, toll-free a CFString, for an attribute's name.
    fn ns_string(text: &CStr) -> *mut AnyObject {
        // SAFETY: a class method that takes a NUL-terminated UTF-8 string.
        unsafe { msg_send![class!(NSString), stringWithUTF8String: text.as_ptr()] }
    }

    /// The Rust text of an NSString (or a toll-free CFString), or None.
    ///
    /// # Safety
    /// `value` is null or an NSString.
    unsafe fn rust_string(value: *const AnyObject) -> Option<String> {
        if value.is_null() {
            return None;
        }
        let utf8: *const std::ffi::c_char = msg_send![value, UTF8String];
        (!utf8.is_null()).then(|| CStr::from_ptr(utf8).to_string_lossy().into_owned())
    }

    /// An accessibility attribute's value, owned by the caller.
    ///
    /// # Safety
    /// `element` is a live AXUIElement.
    unsafe fn attribute(element: CFTypeRef, name: &CStr) -> Option<CFTypeRef> {
        let mut value: CFTypeRef = std::ptr::null();
        let error = AXUIElementCopyAttributeValue(element, ns_string(name).cast(), &mut value);
        (error == 0 && !value.is_null()).then_some(value)
    }

    /// A string attribute's text.
    ///
    /// # Safety
    /// As `attribute`; the attribute is one whose value is a string.
    unsafe fn text(element: CFTypeRef, name: &CStr) -> Option<String> {
        let value = attribute(element, name)?;
        let text = rust_string(value.cast());
        CFRelease(value);
        text
    }

    /// The selected text of the focused element, and the focused window's title.
    fn selection_and_window(pid: i32) -> (Option<String>, Option<String>) {
        // SAFETY: every value copied here is released once, and each element
        // is used only while the one it came from is held.
        unsafe {
            let app = AXUIElementCreateApplication(pid);
            if app.is_null() {
                return (None, None);
            }
            let selection = attribute(app, c"AXFocusedUIElement").and_then(|focused| {
                let selected = text(focused, c"AXSelectedText");
                CFRelease(focused);
                selected
            });
            let window = attribute(app, c"AXFocusedWindow").and_then(|window| {
                let title = text(window, c"AXTitle");
                CFRelease(window);
                title
            });
            CFRelease(app);
            (selection, window)
        }
    }

    fn clipboard() -> Option<String> {
        // SAFETY: the general pasteboard is always there; the type is a constant.
        unsafe {
            let board: *mut AnyObject = msg_send![class!(NSPasteboard), generalPasteboard];
            let text: *mut AnyObject = msg_send![board, stringForType: ns_string(c"public.utf8-plain-text")];
            rust_string(text)
        }
    }

    /// Finder's selection, as paths - asked only when Finder is in front.
    fn finder_selection() -> Vec<PathBuf> {
        let script = "tell application \"Finder\" to set picked to selection as alias list\n\
                      set out to \"\"\n\
                      repeat with f in picked\n\
                      set out to out & POSIX path of f & linefeed\n\
                      end repeat\n\
                      return out";
        let Ok(output) = Command::new("osascript").args(["-e", script]).output() else {
            return Vec::new();
        };
        String::from_utf8_lossy(&output.stdout)
            .lines()
            .map(PathBuf::from)
            .filter(|path| path.is_file())
            .take(MAX_FILES)
            .collect()
    }

    pub fn capture() -> (ActiveContext, Vec<PathBuf>) {
        let mut context = ActiveContext {
            clipboard: clipboard().and_then(cut),
            // SAFETY: a plain query of this process's own trust.
            accessibility: unsafe { AXIsProcessTrusted() },
            ..ActiveContext::default()
        };
        // SAFETY: the shared workspace and its frontmost application, read.
        let (pid, name, bundle) = unsafe {
            let workspace: *mut AnyObject = msg_send![class!(NSWorkspace), sharedWorkspace];
            let front: *mut AnyObject = msg_send![workspace, frontmostApplication];
            if front.is_null() {
                return (context, Vec::new());
            }
            let pid: i32 = msg_send![front, processIdentifier];
            let name: *mut AnyObject = msg_send![front, localizedName];
            let bundle: *mut AnyObject = msg_send![front, bundleIdentifier];
            (pid, rust_string(name), rust_string(bundle))
        };
        // The app itself in front - the console - has nothing to tell quick ask.
        if u32::try_from(pid).ok() == Some(std::process::id()) {
            return (context, Vec::new());
        }
        context.app = name;
        if context.accessibility {
            let (selection, window) = selection_and_window(pid);
            context.selection = selection.and_then(cut);
            context.window = window.filter(|title| !title.trim().is_empty());
        }
        let files = if bundle.as_deref() == Some("com.apple.finder") {
            finder_selection()
        } else {
            Vec::new()
        };
        context.files = files
            .iter()
            .filter_map(|path| path.file_name().map(|name| name.to_string_lossy().into_owned()))
            .collect();
        (context, files)
    }
}

/// Elsewhere quick ask opens with nothing from the app in front: reading
/// another window's selection is a per-platform piece not written yet.
#[cfg(not(target_os = "macos"))]
mod platform {
    use std::path::PathBuf;

    use super::ActiveContext;

    pub fn capture() -> (ActiveContext, Vec<PathBuf>) {
        (ActiveContext::default(), Vec::new())
    }
}

#[cfg(test)]
mod tests {
    use super::{cut, read, ActiveContext, MAX_TEXT_CHARS};

    #[test]
    fn text_is_trimmed_dropped_when_empty_and_cut_when_long() {
        assert_eq!(cut("  hi \n".into()), Some("hi".into()));
        assert_eq!(cut("   ".into()), None);
        assert_eq!(
            cut("x".repeat(MAX_TEXT_CHARS + 50)).map(|t| t.chars().count()),
            Some(MAX_TEXT_CHARS)
        );
    }

    #[test]
    fn a_context_reaches_the_panel_in_the_shape_it_reads() {
        let context = ActiveContext {
            app: Some("Mail".into()),
            files: vec!["a.pdf".into()],
            accessibility: true,
            ..ActiveContext::default()
        };
        let json = serde_json::to_value(&context).unwrap();
        assert_eq!(json["app"], "Mail");
        assert_eq!(json["files"][0], "a.pdf");
        assert_eq!(json["selection"], serde_json::Value::Null);
        assert_eq!(json["accessibility"], true);
    }

    #[test]
    fn a_file_is_read_whole_and_a_missing_one_is_named() {
        let dir = std::env::temp_dir().join(format!("agenticos-context-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("note.txt");
        std::fs::write(&path, "hello").unwrap();
        let file = read(&path).unwrap();
        assert_eq!(file.name, "note.txt");
        assert_eq!(file.data, "aGVsbG8=");
        assert!(read(&dir.join("gone.txt")).unwrap_err().contains("gone.txt"));
        std::fs::remove_dir_all(dir).unwrap();
    }
}
