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
  | { type: `${typeof PREFIX}history` };

export const ASK = `${PREFIX}ask` as const;
export const CONTEXT = `${PREFIX}context` as const;
export const NEW = `${PREFIX}new` as const;
export const HISTORY = `${PREFIX}history` as const;

/** A message from this origin, of a kind the frame knows, or `null`. */
export function readToFrame(event: MessageEvent, origin: string): ToFrame | null {
  if (event.origin !== origin) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null || !("type" in data)) return null;
  const message = data as { type: unknown; text?: unknown; path?: unknown; title?: unknown };
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
  return null;
}
