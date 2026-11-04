//! Optional OS permissions, requested only by the bundled connection wizard.
use serde::{Deserialize, Serialize};
use tauri::AppHandle;

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    ScreenCapture,
    Accessibility,
    Microphone,
}

#[derive(Serialize)]
pub struct Status {
    supported: bool,
    pub(crate) screen_capture: bool,
    pub(crate) accessibility: bool,
    microphone: bool,
}

#[cfg(target_os = "macos")]
#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXIsProcessTrusted() -> bool;
}

#[tauri::command]
pub fn onboarding_permissions() -> Status {
    #[cfg(target_os = "macos")]
    {
        // SAFETY: these OS preflight functions take no pointers and never prompt.
        Status {
            supported: true,
            screen_capture: unsafe { crate::CGPreflightScreenCaptureAccess() },
            accessibility: unsafe { AXIsProcessTrusted() },
            microphone: crate::readiness::microphone_granted(),
        }
    }
    #[cfg(not(target_os = "macos"))]
    Status {
        supported: false,
        screen_capture: false,
        accessibility: false,
        microphone: false,
    }
}

#[tauri::command]
pub async fn request_onboarding_permission(app: AppHandle, permission: Permission) -> Result<Status, String> {
    #[cfg(target_os = "macos")]
    match permission {
        Permission::ScreenCapture => {
            crate::screen_capture_allowed();
        }
        Permission::Accessibility => crate::context::open_accessibility_settings(app)?,
        // Asks macOS for the prompt; once refused, opens the Microphone pane instead.
        Permission::Microphone => {
            crate::readiness::desktop_request_permission(app, crate::readiness::Permission::Microphone).await?
        }
    }
    #[cfg(not(target_os = "macos"))]
    let _ = (app, permission);
    Ok(onboarding_permissions())
}

#[cfg(test)]
mod tests {
    use super::Permission;

    #[test]
    fn only_individually_named_permissions_can_be_requested() {
        assert!(matches!(
            serde_json::from_str::<Permission>("\"screen_capture\""),
            Ok(Permission::ScreenCapture)
        ));
        assert!(matches!(
            serde_json::from_str::<Permission>("\"accessibility\""),
            Ok(Permission::Accessibility)
        ));
        assert!(matches!(
            serde_json::from_str::<Permission>("\"microphone\""),
            Ok(Permission::Microphone)
        ));
        for name in ["all", "camera", "files", "notifications"] {
            assert!(serde_json::from_value::<Permission>(serde_json::json!(name)).is_err());
        }
    }
}
