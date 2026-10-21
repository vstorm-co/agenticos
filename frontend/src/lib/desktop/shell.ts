/**
 * The desktop shell, as the console sees it: whether this page is inside it, and
 * the one door through which the page talks to it.
 *
 * The console is the same Next.js application in a browser and in the shell.
 * The shell announces itself with `window.__AGENTICOS_SHELL__`, set by an
 * initialization script before any script of the page runs, and grants the
 * page's origin a short list of commands (`desktop/src-tauri/src/console.rs`).
 * Everything here reads both at runtime and trusts neither by type: an older
 * shell, a newer one, or a browser with no shell at all are all states this
 * module answers rather than crashes on.
 */

export type ShellPlatform = "macos" | "windows" | "linux";

/** Which of the shell's windows this page is drawn in. */
export type ShellWindow = "main" | "blobby" | "quick-ask";

export interface ShellInfo {
  platform: ShellPlatform;
  version: string;
  window: ShellWindow;
  /** Whether the window can draw a real material behind a glass console. */
  vibrancy: boolean;
}

const PLATFORMS: readonly ShellPlatform[] = ["macos", "windows", "linux"];
const WINDOWS: readonly ShellWindow[] = ["main", "blobby", "quick-ask"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[]): value is T {
  return typeof value === "string" && (allowed as readonly string[]).includes(value);
}

/** The shell's announcement, or `null` for anything that is not one. */
export function parseShellInfo(value: unknown): ShellInfo | null {
  if (!isRecord(value)) return null;
  const { platform, version, window, vibrancy } = value;
  if (!oneOf(platform, PLATFORMS) || !oneOf(window, WINDOWS)) return null;
  if (typeof version !== "string" || typeof vibrancy !== "boolean") return null;
  return { platform, version, window, vibrancy };
}

declare global {
  interface Window {
    __AGENTICOS_SHELL__?: unknown;
    __TAURI__?: unknown;
    /** Defined by the desktop bridge; the shell's menu calls it to change page in place. */
    __agenticosNavigate?: (path: string) => void;
  }
}

/** The shell this page is in, or `null` in a browser (and on the server). */
export function readShellInfo(): ShellInfo | null {
  if (typeof window === "undefined") return null;
  return parseShellInfo(window.__AGENTICOS_SHELL__);
}

/** Why talking to the shell failed: no shell, an answer this console cannot read, or a refusal. */
export type ShellFailure = "unavailable" | "malformed" | "refused";

/**
 * A command the shell refused, a page with no shell to ask, or an answer in a
 * shape this console does not know.
 *
 * The message is for a developer reading the console - the failure, then what
 * failed or the shell's own reason. What a person reads comes from the catalog,
 * chosen by `failure`.
 */
export class ShellError extends Error {
  readonly failure: ShellFailure;

  constructor(failure: ShellFailure, detail: string, options?: { cause?: unknown }) {
    super(`${failure}: ${detail}`, options);
    this.name = "ShellError";
    this.failure = failure;
  }
}

export interface ShellEvent {
  payload: unknown;
}

type Unlisten = () => void;

interface TauriCore {
  invoke: (command: string, args?: Record<string, unknown>) => Promise<unknown>;
  listen: (event: string, handler: (event: ShellEvent) => void) => Promise<Unlisten>;
}

/** Tauri's global API, narrowed to the two functions this module calls. */
function tauri(): TauriCore | null {
  if (typeof window === "undefined" || !isRecord(window.__TAURI__)) return null;
  const { core, event } = window.__TAURI__;
  if (!isRecord(core) || !isRecord(event)) return null;
  const { invoke } = core;
  const { listen } = event;
  if (typeof invoke !== "function" || typeof listen !== "function") return null;
  return {
    invoke: (command, args) => Promise.resolve(invoke(command, args)),
    listen: (name, handler) => Promise.resolve(listen(name, handler)).then(asUnlisten),
  };
}

function asUnlisten(value: unknown): Unlisten {
  if (typeof value !== "function") throw new ShellError("malformed", "unlisten");
  return () => value();
}

/** The message of whatever a command rejected with: the shell rejects with a string. */
function messageOf(reason: unknown): string {
  if (typeof reason === "string") return reason;
  if (reason instanceof Error) return reason.message;
  return String(reason);
}

/** Ask the shell to do something; rejects with a `ShellError` carrying its reason. */
export async function invokeShell(
  command: string,
  args?: Record<string, unknown>,
): Promise<unknown> {
  const core = tauri();
  if (!core) throw new ShellError("unavailable", command);
  try {
    return await core.invoke(command, args);
  } catch (reason) {
    throw new ShellError("refused", messageOf(reason), { cause: reason });
  }
}

/** Listen for an event the shell emits to this window. Resolves to the unlisten. */
export async function listenShell(
  event: string,
  handler: (payload: unknown) => void,
): Promise<Unlisten> {
  const core = tauri();
  if (!core) throw new ShellError("unavailable", event);
  return core.listen(event, ({ payload }) => handler(payload));
}

/**
 * A shell command that failed where nobody is waiting on it - a background sync,
 * a notification - said where a developer looks, never swallowed.
 */
export function reportShellFailure(what: string, error: unknown): void {
  console.warn("desktop", what, error);
}

/** The shell's events, as `console.rs`, `blobby.rs` and `notify.rs` emit them. */
export const SHELL_EVENTS = {
  blobby: "desktop:blobby",
  say: "desktop:say",
  approval: "desktop:approval",
  quickAsk: "desktop:quick-ask",
} as const;
