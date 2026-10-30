//! Native notifications, sent by the console and answered here.
//!
//! The console decides what is worth a notification - it reads the inbox and the
//! approval queue with its own session, and the shell has none - and asks the
//! shell to show it. A click on one opens the console where the notification
//! points. An approval also carries Approve and Reject; the shell cannot decide
//! it either, so the choice goes back to the console window, which makes the same
//! request its own Approve button would.

use std::collections::VecDeque;
use std::sync::atomic::{AtomicI32, Ordering};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_notification::{Action, ActionPerformed, ActionType, NotificationExt};

pub const APPROVAL_EVENT: &str = "desktop:approval";
const APPROVAL_TYPE: &str = "approval";
const APPROVE: &str = "approve";
const REJECT: &str = "reject";
const TAP: &str = "tap";
/// How many notifications are remembered for their click. One that scrolled out
/// of the Notification Centre long ago answers a click by opening the console.
const REMEMBERED: usize = 100;
const MAX_TEXT: usize = 500;

/// A notification the console asks for.
#[derive(Deserialize, Debug, Clone, PartialEq)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Notice {
    /// A row of the inbox: a run that finished or failed, a budget alert, a share.
    Inbox { title: String, body: String, path: String },
    /// A tool call waiting for a decision, decidable from the notification.
    Approval {
        title: String,
        body: String,
        path: String,
        approval_id: String,
        approve_label: String,
        reject_label: String,
    },
}

impl Notice {
    fn path(&self) -> &str {
        match self {
            Notice::Inbox { path, .. } | Notice::Approval { path, .. } => path,
        }
    }
}

/// A decision taken on a notification, for the console to carry out.
#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct Decision {
    pub approval_id: String,
    pub approved: bool,
}

/// What a click on a shown notification leads to.
#[derive(Clone, Debug, PartialEq)]
enum Target {
    Open(String),
    Decide { path: String, approval_id: String },
}

#[derive(Default)]
pub struct Delivered {
    next: AtomicI32,
    shown: Mutex<VecDeque<(i32, Target)>>,
}

impl Delivered {
    fn remember(&self, target: Target) -> i32 {
        let id = self.next.fetch_add(1, Ordering::Relaxed).wrapping_add(1);
        if let Ok(mut shown) = self.shown.lock() {
            if shown.len() == REMEMBERED {
                shown.pop_front();
            }
            shown.push_back((id, target));
        }
        id
    }

    fn target(&self, id: i32) -> Option<Target> {
        let shown = self.shown.lock().ok()?;
        shown
            .iter()
            .find(|(shown_id, _)| *shown_id == id)
            .map(|(_, t)| t.clone())
    }
}

/// What to do about an action on a notification, given where it pointed.
#[derive(Debug, PartialEq)]
pub enum Outcome {
    Open(String),
    Decide(Decision),
    Nothing,
}

fn outcome(action: &str, target: Option<Target>) -> Outcome {
    match (action, target) {
        (APPROVE | REJECT, Some(Target::Decide { approval_id, .. })) => Outcome::Decide(Decision {
            approval_id,
            approved: action == APPROVE,
        }),
        (TAP, Some(Target::Open(path) | Target::Decide { path, .. })) => Outcome::Open(path),
        _ => Outcome::Nothing,
    }
}

/// A path inside the console, and nothing else: a notification is text from the
/// server, and what it opens must stay on the server the person chose.
pub fn is_console_path(path: &str) -> bool {
    path.starts_with('/') && !path.starts_with("//") && !path.contains('\\') && !path.contains("://")
}

fn bounded(text: &str) -> String {
    text.chars().take(MAX_TEXT).collect()
}

pub fn show<R: Runtime>(app: &AppHandle<R>, notice: Notice) -> Result<(), String> {
    if !is_console_path(notice.path()) {
        return Err(format!("{} is not a page of the console.", notice.path()));
    }
    let delivered = app.state::<Delivered>();
    let notifications = app.notification();
    let builder = match &notice {
        Notice::Inbox { title, body, path } => notifications
            .builder()
            .id(delivered.remember(Target::Open(path.clone())))
            .title(bounded(title))
            .body(bounded(body)),
        Notice::Approval {
            title,
            body,
            path,
            approval_id,
            approve_label,
            reject_label,
        } => {
            // Registered on every approval rather than once: the labels are the
            // console's, in the console's language, and the person may have
            // switched it since the last one.
            notifications
                .register_action_types(vec![ActionType::builder(APPROVAL_TYPE)
                    .actions(vec![
                        Action::builder(APPROVE, bounded(approve_label)).build(),
                        Action::builder(REJECT, bounded(reject_label)).destructive(true).build(),
                    ])
                    .build()])
                .map_err(|e| e.to_string())?;
            notifications
                .builder()
                .id(delivered.remember(Target::Decide {
                    path: path.clone(),
                    approval_id: approval_id.clone(),
                }))
                .title(bounded(title))
                .body(bounded(body))
                .action_type_id(APPROVAL_TYPE)
        }
    };
    builder.show().map_err(|e| e.to_string())
}

/// Route an action on a notification: open the console, or hand it a decision.
pub fn on_action(app: &AppHandle, performed: &ActionPerformed) {
    let target = performed
        .notification()
        .and_then(|shown| app.state::<Delivered>().target(shown.id()));
    match outcome(performed.action_id(), target) {
        Outcome::Open(path) => {
            if let Err(e) = crate::open_in_console_at(app, &path) {
                eprintln!("notification: {e}");
            }
        }
        Outcome::Decide(decision) => {
            if let Err(e) = app.emit_to(crate::WINDOW, APPROVAL_EVENT, decision) {
                eprintln!("notification: {e}");
            }
        }
        Outcome::Nothing => {}
    }
}

#[cfg(test)]
mod tests {
    use super::{is_console_path, outcome, Decision, Delivered, Notice, Outcome, Target, REMEMBERED};

    #[test]
    fn a_click_opens_where_the_notification_points() {
        let target = Target::Open("/runs?tab=approvals".into());
        assert_eq!(
            outcome("tap", Some(target)),
            Outcome::Open("/runs?tab=approvals".into())
        );
    }

    #[test]
    fn approve_and_reject_become_decisions_only_on_an_approval() {
        let approval = || {
            Some(Target::Decide {
                path: "/runs".into(),
                approval_id: "ap1".into(),
            })
        };
        assert_eq!(
            outcome("approve", approval()),
            Outcome::Decide(Decision {
                approval_id: "ap1".into(),
                approved: true
            })
        );
        assert_eq!(
            outcome("reject", approval()),
            Outcome::Decide(Decision {
                approval_id: "ap1".into(),
                approved: false
            })
        );
        assert_eq!(outcome("approve", Some(Target::Open("/runs".into()))), Outcome::Nothing);
        assert_eq!(outcome("tap", approval()), Outcome::Open("/runs".into()));
        assert_eq!(outcome("tap", None), Outcome::Nothing);
    }

    #[test]
    fn only_a_path_on_the_console_may_be_opened() {
        assert!(is_console_path("/runs?tab=approvals"));
        assert!(is_console_path("/pl/chat?id=1"));
        assert!(!is_console_path("https://evil.example/"));
        assert!(!is_console_path("//evil.example/x"));
        assert!(!is_console_path("/\\evil.example"));
        assert!(!is_console_path("runs"));
        assert!(!is_console_path("/redirect?to=https://evil.example"));
    }

    #[test]
    fn the_oldest_target_is_forgotten_once_the_memory_is_full() {
        let delivered = Delivered::default();
        let first = delivered.remember(Target::Open("/first".into()));
        for _ in 0..REMEMBERED {
            delivered.remember(Target::Open("/later".into()));
        }
        assert_eq!(delivered.target(first), None);
    }

    #[test]
    fn a_notice_is_read_in_the_shape_the_console_sends() {
        let notice: Notice = serde_json::from_str(
            r#"{"kind":"approval","title":"Support wants to send_email","body":"to: a@b.c","path":"/runs?tab=approvals","approval_id":"ap1","approve_label":"Approve","reject_label":"Reject"}"#,
        )
        .unwrap();
        assert!(matches!(notice, Notice::Approval { ref approval_id, .. } if approval_id == "ap1"));
    }
}
