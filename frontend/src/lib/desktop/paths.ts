/**
 * A path inside the console, and nothing else - the same rule the shell applies
 * (`notify.rs`, `is_console_path`) before it opens one: text from the server
 * must not send the desktop app's window to another site.
 */
export function isConsolePath(path: string): boolean {
  return (
    path.startsWith("/") && !path.startsWith("//") && !path.includes("\\") && !path.includes("://")
  );
}
