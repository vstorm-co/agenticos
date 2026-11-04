import { invokeShell, isDesktopShell, isMobileShell, readShellInfo } from "./shell";

let pending: Promise<void> | null = null;

/** All session-loss paths share native revocation, including expired cookies. */
export function clearNativeAccount(): Promise<void> {
  if (pending) return pending;
  const shell = readShellInfo();
  const command = isDesktopShell(shell)
    ? "device_unlink"
    : isMobileShell(shell)
      ? "clear_push_session"
      : null;
  if (!command) return Promise.resolve();
  pending = invokeShell(command)
    .then(() => undefined)
    .finally(() => {
      pending = null;
    });
  return pending;
}
