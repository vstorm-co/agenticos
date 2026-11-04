/**
 * A tap felt under the finger (#2097) when a gesture does something: a swipe
 * passing the point where letting go decides, a decision landing, a pull
 * passing the point where letting go refreshes.
 *
 * The phone app's own haptics (`tauri-plugin-haptics`), which iOS and Android
 * both have; in a browser, the vibration Android's has and other browsers
 * ignore. Nothing anybody waits on: a tap that fails is said where a developer
 * looks, and the gesture goes on.
 */

import { invokeShell, isMobileShell, readShellInfo, reportShellFailure } from "@/lib/desktop/shell";

/**
 * `threshold`: a gesture crossed the point of no return. `success` and
 * `warning`: what it decided - yes, or no.
 */
export type Haptic = "threshold" | "success" | "warning";

const NATIVE: Record<Haptic, [command: string, args: Record<string, unknown>]> = {
  threshold: ["plugin:haptics|impact_feedback", { style: "medium" }],
  success: ["plugin:haptics|notification_feedback", { type: "success" }],
  warning: ["plugin:haptics|notification_feedback", { type: "warning" }],
};

/** Milliseconds of vibration, for a browser that has nothing finer. */
const VIBRATION: Record<Haptic, number> = { threshold: 10, success: 20, warning: 30 };

export function haptic(kind: Haptic): void {
  if (isMobileShell(readShellInfo())) {
    const [command, args] = NATIVE[kind];
    invokeShell(command, args).catch((error: unknown) => reportShellFailure("haptics", error));
    return;
  }
  if (typeof navigator !== "undefined" && "vibrate" in navigator)
    navigator.vibrate(VIBRATION[kind]);
}
