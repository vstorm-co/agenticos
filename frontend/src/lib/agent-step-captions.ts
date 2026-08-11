/**
 * Human-readable captions narrating what the agent is doing "under the hood"
 * while a tool runs. Used by the live agent-step animation to label each step
 * in plain language.
 *
 * The per-tool wording lives in `tool-catalog.ts` with the rest of what this side
 * knows about a tool - see the note there on why it is one table. What is left here
 * is the fallback for a name the catalog has never heard of: an MCP tool, or one a
 * binding renamed.
 *
 * Both functions take the caller's translator rather than holding copy, because a
 * module cannot call one and the catalog holds keys (#446). The namespace is
 * `chat.tools`: every caller renders inside the chat panel.
 */

import { toolEntry } from "./tool-catalog";

/** What a caller hands over: `useTranslations("chat.tools")`, narrowed to what is used. */
export type Translate = (key: string, values?: Record<string, string | number>) => string;

/** Prefix-based fallbacks for tools like `generate_*`, as `chat.tools` keys. */
const PREFIX_CAPTIONS: ReadonlyArray<readonly [string, string]> = [
  ["generate_", "generatingChart"],
  ["search_", "searching"],
  ["create_", "creating"],
  ["fetch_", "fetchingData"],
  ["get_", "lookingThatUp"],
  ["list_", "lookingThatUp"],
];

function humanizeToolName(name: string): string {
  const words = name.split("_").filter(Boolean);
  if (words.length === 0) return name;
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

export function toolDisplayName(toolName: string, t: Translate): string {
  const key = toolEntry(toolName)?.displayNameKey;
  return key === undefined ? humanizeToolName(toolName) : t(key);
}

/**
 * Present-tense phrase describing what the agent is doing while `toolName` runs.
 * Falls back to "Running <Tool Name>" for unknown tools.
 */
export function toolCaption(toolName: string, t: Translate): string {
  const known = toolEntry(toolName)?.captionKey;
  if (known !== undefined) return t(known);
  for (const [prefix, key] of PREFIX_CAPTIONS) {
    if (toolName.startsWith(prefix)) return t(key);
  }
  return t("runningNamed", { name: humanizeToolName(toolName) });
}
