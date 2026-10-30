//! Agents pinned for a new chat at one click (#2305): "New Chat With" in the
//! tray's menu, and in the Dock icon's menu on macOS. A pinned agent opens the
//! console on `/chat?with=<id>`, which addresses a new chat to it.
//!
//! The shell keeps the list - an id and a name each - so its menus can name
//! them without a session; the console pins and unpins from an agent's page
//! and the desktop settings.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A menu of more than this is a list of agents, which is the console's to show.
pub const MAX_PINNED: usize = 8;
const MAX_NAME_CHARS: usize = 80;
const MENU_PREFIX: &str = "pinned-agent-";

#[derive(Serialize, Deserialize, Clone, PartialEq, Eq, Debug)]
pub struct PinnedAgent {
    pub id: String,
    pub name: String,
}

/// An agent as the console sent it, or why it cannot be pinned: the id goes
/// into a console path and the name into a menu, so both are checked.
pub fn validate(agent: &PinnedAgent) -> Result<PinnedAgent, String> {
    let id = Uuid::parse_str(&agent.id).map_err(|_| "An agent's id is a UUID.".to_owned())?;
    let name = agent.name.trim();
    if name.is_empty() || name.chars().any(char::is_control) {
        return Err("An agent's name is needed, on one line.".to_owned());
    }
    Ok(PinnedAgent {
        id: id.to_string(),
        name: name.chars().take(MAX_NAME_CHARS).collect(),
    })
}

/// The list with `agent` pinned: last, or renamed where it already was.
pub fn pin(pinned: &[PinnedAgent], agent: PinnedAgent) -> Result<Vec<PinnedAgent>, String> {
    let mut next = pinned.to_vec();
    if let Some(existing) = next.iter_mut().find(|kept| kept.id == agent.id) {
        existing.name = agent.name;
        return Ok(next);
    }
    if next.len() >= MAX_PINNED {
        return Err(format!("At most {MAX_PINNED} agents can be pinned."));
    }
    next.push(agent);
    Ok(next)
}

pub fn unpin(pinned: &[PinnedAgent], id: &str) -> Vec<PinnedAgent> {
    pinned.iter().filter(|kept| kept.id != id).cloned().collect()
}

pub fn menu_id(agent: &PinnedAgent) -> String {
    format!("{MENU_PREFIX}{}", agent.id)
}

/// The agent a menu item names, by its id.
pub fn from_menu_id(id: &str) -> Option<&str> {
    id.strip_prefix(MENU_PREFIX)
}

/// Where a pinned agent opens: a new chat addressed to it.
pub fn chat_path(id: &str) -> String {
    format!("/chat?with={id}")
}

/// The Dock icon's menu, which Tauri has no API for: `applicationDockMenu:`
/// added to the application delegate's class, answering with the pinned
/// agents. AppKit asks for it each time the menu opens, so it is built from
/// the list as it is then.
#[cfg(target_os = "macos")]
pub mod dock {
    use std::ffi::CString;
    use std::sync::{Mutex, OnceLock};

    use objc2::runtime::{AnyObject, Imp, Sel};
    use objc2::{class, msg_send, sel};
    use tauri::AppHandle;

    use super::{chat_path, PinnedAgent};

    static APP: OnceLock<AppHandle> = OnceLock::new();
    /// What the next menu lists; an item's tag is its place here.
    static PINNED: Mutex<Vec<PinnedAgent>> = Mutex::new(Vec::new());

    pub fn set(pinned: &[PinnedAgent]) {
        if let Ok(mut held) = PINNED.lock() {
            *held = pinned.to_vec();
        }
    }

    /// An autoreleased NSString, or `nil` for text with a NUL in it.
    fn ns_string(text: &str) -> *mut AnyObject {
        let Ok(text) = CString::new(text) else {
            return std::ptr::null_mut();
        };
        // SAFETY: a class method taking a NUL-terminated UTF-8 string.
        unsafe { msg_send![class!(NSString), stringWithUTF8String: text.as_ptr()] }
    }

    unsafe extern "C-unwind" fn dock_menu(this: *mut AnyObject, _: Sel, _app: *mut AnyObject) -> *mut AnyObject {
        let pinned = PINNED.lock().map(|held| held.clone()).unwrap_or_default();
        if pinned.is_empty() {
            return std::ptr::null_mut();
        }
        // SAFETY: AppKit calls this on the main thread. The menu is returned
        // autoreleased, as the method's convention is; each item is released
        // once the menu holds it.
        unsafe {
            let menu: *mut AnyObject = msg_send![class!(NSMenu), alloc];
            let menu: *mut AnyObject = msg_send![menu, initWithTitle: ns_string("")];
            let heading: *mut AnyObject = msg_send![class!(NSMenuItem), alloc];
            let heading: *mut AnyObject = msg_send![heading, initWithTitle: ns_string("New Chat With"), action: None::<Sel>, keyEquivalent: ns_string("")];
            let _: () = msg_send![heading, setEnabled: false];
            let _: () = msg_send![menu, addItem: heading];
            let _: () = msg_send![heading, release];
            for (index, agent) in pinned.iter().enumerate() {
                let item: *mut AnyObject = msg_send![class!(NSMenuItem), alloc];
                let item: *mut AnyObject = msg_send![item, initWithTitle: ns_string(&agent.name), action: sel!(agenticosOpenPinned:), keyEquivalent: ns_string("")];
                let _: () = msg_send![item, setTarget: this];
                let _: () = msg_send![item, setTag: index as isize];
                let _: () = msg_send![item, setIndentationLevel: 1isize];
                let _: () = msg_send![menu, addItem: item];
                let _: () = msg_send![item, release];
            }
            msg_send![menu, autorelease]
        }
    }

    unsafe extern "C-unwind" fn open_pinned(_this: *mut AnyObject, _: Sel, item: *mut AnyObject) {
        // SAFETY: AppKit hands the menu item that was chosen.
        let tag: isize = unsafe { msg_send![item, tag] };
        let id = PINNED.lock().ok().and_then(|held| {
            usize::try_from(tag)
                .ok()
                .and_then(|i| held.get(i).map(|agent| agent.id.clone()))
        });
        if let (Some(app), Some(id)) = (APP.get(), id) {
            if let Err(e) = crate::open_in_console_at(app, &chat_path(&id)) {
                eprintln!("{e}");
            }
        }
    }

    /// Give the application delegate the Dock menu. Once, on the main thread,
    /// after the event loop has made its delegate.
    pub fn install(app: &AppHandle, pinned: &[PinnedAgent]) {
        set(pinned);
        if APP.set(app.clone()).is_err() {
            return;
        }
        // SAFETY: the shared application and its delegate, read on the main
        // thread; the two methods added have the signatures their type
        // encodings say, and the delegate's class answers neither already.
        unsafe {
            let ns_app: *mut AnyObject = msg_send![class!(NSApplication), sharedApplication];
            let delegate: *mut AnyObject = msg_send![ns_app, delegate];
            if delegate.is_null() {
                eprintln!("dock menu: the application has no delegate");
                return;
            }
            let class = objc2::ffi::object_getClass(delegate).cast_mut();
            let menu = std::mem::transmute::<
                unsafe extern "C-unwind" fn(*mut AnyObject, Sel, *mut AnyObject) -> *mut AnyObject,
                Imp,
            >(dock_menu);
            let open = std::mem::transmute::<unsafe extern "C-unwind" fn(*mut AnyObject, Sel, *mut AnyObject), Imp>(
                open_pinned,
            );
            if !objc2::ffi::class_addMethod(class, sel!(applicationDockMenu:), menu, c"@@:@".as_ptr()).as_bool()
                || !objc2::ffi::class_addMethod(class, sel!(agenticosOpenPinned:), open, c"v@:@".as_ptr()).as_bool()
            {
                eprintln!("dock menu: the delegate already answers it");
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{chat_path, from_menu_id, menu_id, pin, unpin, validate, PinnedAgent, MAX_PINNED};

    fn agent(n: u8, name: &str) -> PinnedAgent {
        PinnedAgent {
            id: format!("00000000-0000-4000-8000-0000000000{n:02}"),
            name: name.to_owned(),
        }
    }

    #[test]
    fn an_agent_is_pinned_with_a_uuid_and_a_one_line_name() {
        let ok = validate(&agent(1, "  Support  ")).unwrap();
        assert_eq!(ok.name, "Support");
        assert!(validate(&PinnedAgent {
            id: "../settings".into(),
            name: "x".into()
        })
        .is_err());
        assert!(validate(&agent(1, "   ")).is_err());
        assert!(validate(&agent(1, "two\nlines")).is_err());
        assert_eq!(validate(&agent(1, &"n".repeat(200))).unwrap().name.chars().count(), 80);
    }

    #[test]
    fn pinning_again_renames_and_the_list_has_a_ceiling() {
        let one = pin(&[], agent(1, "Support")).unwrap();
        let renamed = pin(&one, agent(1, "Help desk")).unwrap();
        assert_eq!(renamed, vec![agent(1, "Help desk")]);

        let full: Vec<_> = (0..MAX_PINNED as u8).map(|n| agent(n, "a")).collect();
        assert!(pin(&full, agent(99, "one more")).is_err());
        assert_eq!(unpin(&full, &agent(0, "a").id).len(), MAX_PINNED - 1);
    }

    #[test]
    fn a_menu_item_names_its_agent_and_opens_a_chat_with_it() {
        let support = agent(1, "Support");
        assert_eq!(from_menu_id(&menu_id(&support)), Some(support.id.as_str()));
        assert_eq!(from_menu_id("new-chat"), None);
        assert_eq!(chat_path(&support.id), format!("/chat?with={}", support.id));
    }
}
