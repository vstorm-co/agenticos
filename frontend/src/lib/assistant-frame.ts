import { localePrefixOf } from "@/lib/locale-routing";

/**
 * Where the AI Architect's conversation is rendered for the corner widget (#2063).
 *
 * A page of its own, framed by the console: the chat brings its stores, its
 * socket and its approval and question cards, and a second copy of all of it
 * in the same window would share - and overwrite - the main chat's state.
 */
export const ASSISTANT_FRAME_PATH = "/assistant-frame";

/** The Builder's test panel, framed for the same reason (#2074). */
export const AGENT_TEST_FRAME_PATH = "/agent-test-frame";

/** The only routes the console lets itself frame, and only from itself. */
export const CONSOLE_FRAME_PATHS = [ASSISTANT_FRAME_PATH, AGENT_TEST_FRAME_PATH];

/** Whether `pathname` - with or without a locale prefix - is one of the console's frames. */
export function isConsoleFramePath(pathname: string): boolean {
  const locale = localePrefixOf(pathname);
  const bare = locale ? pathname.slice(locale.length + 1) || "/" : pathname;
  return CONSOLE_FRAME_PATHS.includes(bare);
}

/** Whether this document is the assistant's frame, rather than the console around it. */
export function inAssistantFrame(): boolean {
  return typeof window !== "undefined" && window.self !== window.top;
}
