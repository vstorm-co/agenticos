/**
 * What the console and the AI Architect's frame say to each other (#2063).
 *
 * `postMessage` between two documents of one origin, so each side checks the
 * sender's origin and ignores anything it does not recognise - a stray message
 * from an extension must not send a prompt in somebody's name.
 */

const PREFIX = "agenticos:assistant:";

export type ToFrame =
  /** Send this prompt as the reader. */
  | { type: `${typeof PREFIX}ask`; text: string }
  /** The page the reader is on, for "What am I looking at?". */
  | { type: `${typeof PREFIX}context`; path: string; title: string }
  /** Start a new conversation. */
  | { type: `${typeof PREFIX}new` }
  /** Show or hide the list of earlier conversations. */
  | { type: `${typeof PREFIX}history` }
  /** Attach this file - a screenshot of the page - to the next message. */
  | { type: `${typeof PREFIX}attach`; file: File };

export const ASK = `${PREFIX}ask` as const;
export const CONTEXT = `${PREFIX}context` as const;
export const NEW = `${PREFIX}new` as const;
export const HISTORY = `${PREFIX}history` as const;
export const ATTACH = `${PREFIX}attach` as const;

/** A message from this origin, of a kind the frame knows, or `null`. */
export function readToFrame(event: MessageEvent, origin: string): ToFrame | null {
  if (event.origin !== origin) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null || !("type" in data)) return null;
  const message = data as {
    type: unknown;
    text?: unknown;
    path?: unknown;
    title?: unknown;
    file?: unknown;
  };
  if (message.type === ASK && typeof message.text === "string") {
    return { type: ASK, text: message.text };
  }
  if (
    message.type === CONTEXT &&
    typeof message.path === "string" &&
    typeof message.title === "string"
  ) {
    return { type: CONTEXT, path: message.path, title: message.title };
  }
  if (message.type === NEW) return { type: NEW };
  if (message.type === HISTORY) return { type: HISTORY };
  if (message.type === ATTACH && message.file instanceof File) {
    return { type: ATTACH, file: message.file };
  }
  return null;
}

/** Open a console page the Architect linked to, in the console (#2063). */
export const NAVIGATE = `${PREFIX}navigate` as const;

export type FromFrame = { type: typeof NAVIGATE; href: string };

/** A message from the frame, of a kind the console knows, or `null`. */
export function readFromFrame(
  event: MessageEvent,
  origin: string,
  frame: Window | null | undefined,
): FromFrame | null {
  if (event.origin !== origin || frame == null || event.source !== frame) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null || !("type" in data)) return null;
  const message = data as { type: unknown; href?: unknown };
  if (message.type === NAVIGATE && typeof message.href === "string") {
    return { type: NAVIGATE, href: message.href };
  }
  return null;
}
