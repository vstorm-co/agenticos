/**
 * A call waiting on a person, reduced to what that person weighs first.
 *
 * Who is asking and what for is a sentence; the arguments are the evidence, and
 * a page of them leads with nothing. So a call is read as its service (for a
 * tool from an MCP server), its action in words, and the one argument that says
 * what it is about - the query, the command, the address - with everything else
 * folded behind it and the empty fields an MCP schema always sends left out.
 */

import { BRAND_GLYPHS } from "@/lib/brand-glyphs.generated";
import { MCP_LOGOS } from "@/lib/mcp-logos.generated";

/** Which service a tool belongs to and what it does there, in words. */
export interface ServiceAction {
  /** The service's key - the prefix an MCP tool carries - or null for a built-in tool. */
  service: string | null;
  /** "Search", "Create pages" - the server's tool name without the prefix. */
  action: string;
}

/** Whether this console knows a service by that name - a logo or a brand mark for it. */
export function knownService(service: string): boolean {
  const key = service.toLowerCase();
  return (
    key in BRAND_GLYPHS || Object.keys(MCP_LOGOS).some((host) => host.split(".").includes(key))
  );
}

/** "create-pages" -> "Create pages": a sentence, not a title. */
function sentence(words: string[]): string {
  const text = words.join(" ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * The service and action an MCP tool name carries.
 *
 * MCP tools reach a run as `<service>_<server's own name>`, and a server often
 * repeats itself: Notion's search is `notion_notion-search`. The service's name
 * is dropped from the action so that reads "Search", not "Notion notion search".
 * A built-in tool (`known`) has no service; it keeps the catalog's own name.
 */
export function serviceAction(toolName: string, known: boolean): ServiceAction {
  const cut = toolName.indexOf("_");
  if (known || cut <= 0) return { service: null, action: toolName };
  const service = toolName.slice(0, cut);
  // A prefix is a service only where something says so - a mark this console
  // draws for it, or the hyphenated names MCP servers use and our own tools
  // never do. Otherwise `send_email` would read as "Email" in a service called
  // "send".
  if (!knownService(service) && !toolName.slice(cut + 1).includes("-")) {
    return { service: null, action: toolName };
  }
  const words = toolName
    .slice(cut + 1)
    .split(/[-_]+/)
    .filter((word) => word !== "" && word.toLowerCase() !== service.toLowerCase());
  if (words.length === 0) return { service: null, action: toolName };
  return { service, action: sentence(words) };
}

/** The arguments that say what a call is about, most telling first. */
const TELLING = [
  "command",
  "cmd",
  "query",
  "q",
  "url",
  "path",
  "file_path",
  "title",
  "subject",
  "name",
  "to",
  "text",
  "content",
  "message",
  "prompt",
  "task",
];

/** How much of the telling argument the line shows before it stops. */
const SUMMARY_LENGTH = 160;

/**
 * The one line that says what the call is about, or null when nothing does.
 *
 * Its first line only: a script's first line is the command, and the rest is
 * what the details are for.
 */
export function callSummary(args: Record<string, unknown>): string | null {
  const strings = Object.entries(args).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].trim() !== "",
  );
  const telling =
    TELLING.map((key) => strings.find(([name]) => name === key)).find(Boolean) ?? strings[0];
  if (telling === undefined) return null;
  const line = telling[1].trim().split("\n")[0]!.trim();
  return line.length > SUMMARY_LENGTH ? `${line.slice(0, SUMMARY_LENGTH - 1)}…` : line;
}

/** Whether a value says nothing: an empty string, list or object, or no value. */
function empty(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim() === "";
  if (Array.isArray(value)) return value.every(empty);
  if (typeof value === "object") return Object.values(value).every(empty);
  return false;
}

/**
 * The arguments with every field that says nothing taken out, at every depth.
 *
 * An MCP schema sends its whole shape - `"page_url": ""`, `"teamspace_ids": []`
 * - and a person reading them for the one that matters reads past a dozen blanks.
 */
export function spokenArgs(args: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(args)) {
    if (empty(value)) continue;
    out[name] =
      value !== null && typeof value === "object" && !Array.isArray(value)
        ? spokenArgs(value as Record<string, unknown>)
        : value;
  }
  return out;
}
