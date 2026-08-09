/**
 * Human-readable captions narrating what the agent is doing "under the hood"
 * while a tool runs. Used by the live agent-step animation to label each step
 * in plain language.
 *
 * The per-tool wording lives in `tool-catalog.ts` with the rest of what this side
 * knows about a tool - see the note there on why it is one table. What is left here
 * is the fallback for a name the catalog has never heard of: an MCP tool, or one a
 * binding renamed.
 */

import { toolEntry } from "./tool-catalog";

/** Prefix-based fallbacks for tools like `generate_*`. */
const PREFIX_CAPTIONS: ReadonlyArray<readonly [string, string]> = [
  ["generate_", "Generating a chart"],
  ["search_", "Searching"],
  ["create_", "Creating"],
  ["fetch_", "Fetching data"],
  ["get_", "Looking that up"],
  ["list_", "Looking that up"],
];

function humanizeToolName(name: string): string {
  const words = name.split("_").filter(Boolean);
  if (words.length === 0) return name;
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

export function toolDisplayName(toolName: string): string {
  return toolEntry(toolName)?.displayName ?? humanizeToolName(toolName);
}

/**
 * Present-tense phrase describing what the agent is doing while `toolName` runs.
 * Falls back to "Running <Tool Name>" for unknown tools.
 */
export function toolCaption(toolName: string): string {
  const known = toolEntry(toolName)?.caption;
  if (known !== undefined) return known;
  for (const [prefix, caption] of PREFIX_CAPTIONS) {
    if (toolName.startsWith(prefix)) return caption;
  }
  return `Running ${humanizeToolName(toolName)}`;
}
