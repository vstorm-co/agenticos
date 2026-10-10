import { localePrefixOf } from "@/lib/locale-routing";

/**
 * Where the AI Architect's conversation is rendered for the corner widget (#2063).
 *
 * A page of its own, framed by the console: the chat brings its stores, its
 * socket and its approval and question cards, and a second copy of all of it
 * in the same window would share - and overwrite - the main chat's state. This
 * is the one route the console lets itself frame.
 */
export const ASSISTANT_FRAME_PATH = "/assistant-frame";

/** Whether `pathname` - with or without a locale prefix - is the assistant's frame. */
export function isAssistantFramePath(pathname: string): boolean {
  const locale = localePrefixOf(pathname);
  const bare = locale ? pathname.slice(locale.length + 1) || "/" : pathname;
  return bare === ASSISTANT_FRAME_PATH;
}

/** Whether this document is the assistant's frame, rather than the console around it. */
export function inAssistantFrame(): boolean {
  return typeof window !== "undefined" && window.self !== window.top;
}
