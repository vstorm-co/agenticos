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

/** Whether a tool name is this deployment's own platform tool, `agenticos_<action>`. */
export function isPlatformTool(toolName: string): boolean {
  return toolName.startsWith("agenticos_") && toolName.length > "agenticos_".length;
}

const QUOTE_ARGUMENTS = ["quoted_usd", "estimate_usd", "total_usd"] as const;

/**
 * The price a paid platform call was quoted at, as the decimal string it carries;
 * `null` for any other call. Paid starts compare their current estimate with this
 * quote; the quote is not a provider bill cap.
 */
export function quotedPrice(
  toolName: string,
  args: Record<string, unknown>,
  context?: Record<string, string> | null,
): string | null {
  if (!isPlatformTool(toolName) || context?.platform_tool !== "true") return null;
  for (const name of QUOTE_ARGUMENTS) {
    const value = args[name];
    if (
      typeof value === "string" &&
      value.trim() !== "" &&
      Number.isFinite(Number(value)) &&
      Number(value) >= 0
    )
      return value;
    if (typeof value === "number" && Number.isFinite(value) && value >= 0) return String(value);
  }
  return null;
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
  if (toolName.startsWith("agenticos_") && toolName.length > "agenticos_".length) {
    return {
      service: "AgenticOS",
      action: sentence(toolName.slice("agenticos_".length).split("_")),
    };
  }
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
 * what the details are for. Inbox may omit opaque IDs; decision cards retain
 * them when the caller cannot read the resource's name.
 */
export function callSummary(
  args: Record<string, unknown>,
  { omitOpaqueIds = false }: { omitOpaqueIds?: boolean } = {},
): string | null {
  const value = summaryValue(args, 0, true, omitOpaqueIds);
  if (value === null) return null;
  const line = value.trim().split("\n")[0]!.trim();
  return line.length > SUMMARY_LENGTH ? `${line.slice(0, SUMMARY_LENGTH - 1)}…` : line;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function summaryText(value: string, depth: number, omitOpaqueIds: boolean): string | null {
  const text = value.trim();
  if (!text || (omitOpaqueIds && /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i.test(text)))
    return null;
  if (!/^[\[{]/.test(text)) return text;
  // Some MCP schemas carry the entire search request as a JSON string.
  // Decode only bounded objects; opaque requests belong in the full details.
  if (depth >= 2 || text.length > 8192) return null;
  let decoded: unknown;
  try {
    decoded = JSON.parse(text);
  } catch {
    // Brackets and braces also start shell commands and ordinary subjects.
    // Preserve unparsed text so an approver can still see what will execute.
    return text;
  }
  return isRecord(decoded) ? summaryValue(decoded, depth + 1, false, omitOpaqueIds) : null;
}

function summaryValue(
  args: Record<string, unknown>,
  depth: number,
  allowFallback: boolean,
  omitOpaqueIds: boolean,
): string | null {
  const strings = Object.entries(args).filter(
    (entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].trim() !== "",
  );
  for (const key of TELLING) {
    const telling = strings.find(([name]) => name === key);
    if (telling === undefined) continue;
    const subject =
      key === "command" || key === "cmd"
        ? telling[1].trim()
        : summaryText(telling[1], depth, omitOpaqueIds);
    if (subject !== null) return subject;
  }
  if (Array.isArray(args.filterGroups)) {
    const subjects = args.filterGroups.flatMap((group: unknown) => {
      if (!isRecord(group) || !Array.isArray(group.filters)) return [];
      return group.filters.flatMap((filter: unknown) => {
        if (!isRecord(filter) || typeof filter.value !== "string") return [];
        const subject = summaryText(filter.value, 2, omitOpaqueIds);
        return subject === null ? [] : [subject];
      });
    });
    if (subjects.length > 0) return [...new Set(subjects)].slice(0, 3).join(" · ");
  }
  // Platform writes wrap their subject in a typed payload. Prefer its title
  // over a top-level table UUID, and keep arbitrary nested schemas out of view.
  if (depth < 2) {
    for (const key of ["task", "record", "data", "draft", "payload", "values"]) {
      const nested = args[key];
      if (!isRecord(nested)) continue;
      const subject = summaryValue(nested, depth + 1, allowFallback, omitOpaqueIds);
      if (subject !== null) return subject;
    }
  }
  if (allowFallback) {
    for (const [, value] of strings) {
      const subject = summaryText(value, depth, omitOpaqueIds);
      if (subject !== null) return subject;
    }
  }
  return null;
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
