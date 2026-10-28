//! Non-prompting readiness probes and explicitly requested macOS repairs.
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};
#[cfg(target_os = "macos")]
use tauri_plugin_opener::OpenerExt;

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum PermissionState {
    Granted,
    Denied,
    NotDetermined,
    Unsupported,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    ScreenCapture,
    Accessibility,
    Microphone,
    Notifications,
}

#[derive(Serialize)]
pub struct Readiness {
    connection_revision: String,
    screen_capture: PermissionState,
    accessibility: PermissionState,
    microphone: PermissionState,
    notifications: PermissionState,
}

#[tauri::command]
pub async fn desktop_readiness(app: AppHandle) -> Result<Readiness, String> {
    #[cfg(target_os = "macos")]
    let (screen_capture, accessibility, microphone, notifications) = (
        if unsafe { crate::CGPreflightScreenCaptureAccess() } {
            PermissionState::Granted
        } else {
            PermissionState::Denied
        },
        if unsafe { mac::AXIsProcessTrusted() } {
            PermissionState::Granted
        } else {
            PermissionState::Denied
        },
        mac::microphone(),
        mac::notifications().await?,
    );
    #[cfg(not(target_os = "macos"))]
    let (screen_capture, accessibility, microphone, notifications) = (
        PermissionState::Unsupported,
        PermissionState::Unsupported,
        PermissionState::Unsupported,
        PermissionState::Unsupported,
    );
    Ok(Readiness {
        connection_revision: crate::settings::current(&app).connection_revision,
        screen_capture,
        accessibility,
        microphone,
        notifications,
    })
}

#[tauri::command]
pub async fn desktop_request_permission(app: AppHandle, permission: Permission) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    match permission {
        Permission::ScreenCapture => {
            if !crate::screen_capture_allowed() {
                desktop_open_permission_settings(app, permission)?;
            }
        }
        Permission::Accessibility => desktop_open_permission_settings(app, permission)?,
        Permission::Microphone => {
            if !mac::request_microphone().await? {
                desktop_open_permission_settings(app, permission)?;
            }
        }
        Permission::Notifications => {
            if !mac::request_notifications().await? {
                desktop_open_permission_settings(app, permission)?;
            }
        }
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = (app, permission);
        Err("Permission setup is managed by your operating system.".into())
    }
    #[cfg(target_os = "macos")]
    Ok(())
}

#[cfg(target_os = "macos")]
fn desktop_open_permission_settings(app: AppHandle, permission: Permission) -> Result<(), String> {
    let url = match permission {
        Permission::ScreenCapture => "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        Permission::Accessibility => "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
        Permission::Microphone => "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone",
        Permission::Notifications => "x-apple.systempreferences:com.apple.Notifications-Settings.extension",
    };
    app.opener().open_url(url, None::<&str>).map_err(|e| e.to_string())
}

#[derive(Serialize)]
pub struct Focus {
    focused: bool,
    conversation_id: Option<String>,
}
/// Check both conversation windows, rather than the web document's focus state.
#[tauri::command]
pub fn desktop_is_focused(app: AppHandle) -> Result<Focus, String> {
    for label in [crate::WINDOW, crate::quick_ask::WINDOW] {
        if let Some(window) = app.get_webview_window(label) {
            if window.is_focused().map_err(|e| e.to_string())? {
                return Ok(Focus {
                    focused: true,
                    conversation_id: crate::activity::conversation(&app, label),
                });
            }
        }
    }
    Ok(Focus {
        focused: false,
        conversation_id: None,
    })
}

#[cfg(target_os = "macos")]
mod mac {
    use super::PermissionState;
    use block2::RcBlock;
    use objc2::{
        class, msg_send,
        runtime::{AnyObject, Bool},
    };
    use std::sync::{Arc, Mutex};

    #[link(name = "ApplicationServices", kind = "framework")]
    extern "C" {
        pub fn AXIsProcessTrusted() -> bool;
    }
    #[link(name = "AVFoundation", kind = "framework")]
    extern "C" {
        static AVMediaTypeAudio: *mut AnyObject;
    }
    #[link(name = "UserNotifications", kind = "framework")]
    extern "C" {}

    pub(super) fn notification_state(value: isize) -> PermissionState {
        match value {
            0 => PermissionState::NotDetermined,
            2..=4 => PermissionState::Granted,
            _ => PermissionState::Denied,
        }
    }
    pub(super) fn microphone() -> PermissionState {
        // SAFETY: AVCaptureDevice's class method only reads the app's audio authorization.
        let value: isize =
            unsafe { msg_send![class!(AVCaptureDevice), authorizationStatusForMediaType: AVMediaTypeAudio] };
        match value {
            0 => PermissionState::NotDetermined,
            3 => PermissionState::Granted,
            _ => PermissionState::Denied,
        }
    }
    pub(super) async fn notifications() -> Result<PermissionState, String> {
        let (send, receive) = tokio::sync::oneshot::channel();
        let send = Arc::new(Mutex::new(Some(send)));
        {
            let block = RcBlock::new(move |settings: *mut AnyObject| {
                let result = if settings.is_null() {
                    Err("Cannot read notification settings.".to_string())
                } else {
                    // SAFETY: UserNotifications supplies a valid UNNotificationSettings for this callback.
                    Ok(notification_state(unsafe { msg_send![settings, authorizationStatus] }))
                };
                if let Some(send) = send.lock().unwrap_or_else(|e| e.into_inner()).take() {
                    let _ = send.send(result);
                }
            });
            // SAFETY: macOS copies the completion block before returning; it retains its sender.
            unsafe {
                let center: *mut AnyObject = msg_send![class!(UNUserNotificationCenter), currentNotificationCenter];
                let _: () = msg_send![center, getNotificationSettingsWithCompletionHandler: &*block];
            }
        }
        tokio::time::timeout(std::time::Duration::from_secs(5), receive)
            .await
            .map_err(|_| "Notification status timed out.".to_string())?
            .map_err(|e| e.to_string())?
    }
    async fn request(audio: bool) -> Result<bool, String> {
        let (send, receive) = tokio::sync::oneshot::channel();
        let send = Arc::new(Mutex::new(Some(send)));
        let deliver = move |result: Result<bool, String>| {
            if let Some(send) = send.lock().unwrap_or_else(|e| e.into_inner()).take() {
                let _ = send.send(result);
            }
        };
        if audio {
            let block = RcBlock::new(move |allowed: Bool| deliver(Ok(allowed.as_bool())));
            // SAFETY: AVFoundation copies the completion block; permission is requested only on a user click.
            unsafe {
                let _: () = msg_send![class!(AVCaptureDevice), requestAccessForMediaType: AVMediaTypeAudio, completionHandler: &*block];
            }
        } else {
            let block = RcBlock::new(move |allowed: Bool, error: *mut AnyObject| {
                deliver(if error.is_null() {
                    Ok(allowed.as_bool())
                } else {
                    Err("macOS could not request notification authorization.".to_string())
                });
            });
            // SAFETY: the system owns the copied completion block and authorization dialog.
            unsafe {
                let center: *mut AnyObject = msg_send![class!(UNUserNotificationCenter), currentNotificationCenter];
                let _: () = msg_send![center, requestAuthorizationWithOptions: 7usize, completionHandler: &*block];
            }
        }
        // A user can leave the OS prompt open; don't strand the UI forever.
        tokio::time::timeout(std::time::Duration::from_secs(120), receive)
            .await
            .map_err(|_| "Permission request is still waiting in System Settings.".to_string())?
            .map_err(|e| e.to_string())?
    }
    pub(super) async fn request_microphone() -> Result<bool, String> {
        request(true).await
    }
    pub(super) async fn request_notifications() -> Result<bool, String> {
        request(false).await
    }

    #[test]
    fn notification_authorization_is_not_assumed_granted() {
        assert_eq!(notification_state(0), PermissionState::NotDetermined);
        assert_eq!(notification_state(1), PermissionState::Denied);
        for value in [2, 3, 4] {
            assert_eq!(notification_state(value), PermissionState::Granted);
        }
    }
}
