import type { DesktopState } from "@/lib/desktop/commands";
import type { ShellInfo } from "@/lib/desktop/shell";

/** A desktop app's state as the settings tabs read it, for tests to start from. */
export const DESKTOP_STATE: DesktopState = {
  appearance: { look: "standard", mode: "system" },
  blobby: {
    enabled: true,
    character: { kind: "cast", id: "pebble" },
    chatter: "normal",
    activity: true,
    roams: true,
    size: 1,
    position: null,
  },
  shortcuts: [
    { action: "quick_ask", accelerator: "Alt+Space", problem: null },
    { action: "screenshot_chat", accelerator: "CmdOrCtrl+Shift+A", problem: null },
  ],
  window: { keep_running: true, badge: true, launch_at_login: false },
};

export const MAC_MAIN: ShellInfo = {
  platform: "macos",
  version: "0.2.0",
  window: "main",
  vibrancy: true,
};
