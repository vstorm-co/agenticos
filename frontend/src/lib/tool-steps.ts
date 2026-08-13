/**
 * What one tool call is doing, in a sentence somebody reading the chat would write.
 *
 * The transcript is a narration, so a step reads as one line: *Writing test1.md*
 * while it runs, *Wrote test1.md* once it has. That pair is the whole design. A
 * label fixed in the present tense lies the moment the call finishes, and one fixed
 * in the past lies while it is still going - and the card that used to sit here did
 * both, by showing "Write File" and the JSON it was called with.
 *
 * The subject matters more than the verb: *Writing test1.md* is the useful line, and
 * `write_file` is not. So each tool's own arguments are read for the one thing it is
 * about - a path, a pattern, a command - and the generic caption is the fallback for
 * a tool nothing here knows.
 *
 * The per-tool half of that - the icon, the wording, the tense pair - is one table in
 * `tool-catalog.ts`, keyed on the id the backend registers. What is left here is the
 * logic: which of a call's arguments is its subject, and how an MCP tool is named.
 *
 * Dependency-free on purpose: this is the vocabulary, not the presentation, and the
 * live step animation, the step row and any test can all read it.
 *
 * `toolStep` takes the caller's `chat` translator: the wording is in the catalog and a
 * module cannot reach one (#446).
 */

import { toolCaption, toolDisplayName, type Translate } from "./agent-step-captions";
import { toolEntry, type StepKind } from "./tool-catalog";

export interface ToolStep {
  /** One line: what this call is doing, or did. */
  label: string;
  /** The subject shown after the label when there is one worth repeating. */
  detail: string | null;
  kind: StepKind;
  /** The MCP server's domain, when the step is one of its tools. */
  logoDomain?: string | null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() !== "" ? value.trim() : null;
}

/** The last segment of a path, which is what a person calls the file. */
export function basename(path: string): string {
  return path.split("/").filter(Boolean).pop() ?? path;
}

/** The path this call is about, as the tool was given it. */
export function pathArg(args: Record<string, unknown> | undefined): string | null {
  const given = args ?? {};
  return text(given.path) ?? text(given.file_path) ?? text(given.filename);
}

/** The body a write or an edit is putting into the file. */
export function contentArg(args: Record<string, unknown> | undefined): string | null {
  const given = args ?? {};
  return (
    text(given.content) ?? text(given.text) ?? text(given.new_string) ?? text(given.new_str) ?? null
  );
}

/**
 * One MCP server, as far as naming a tool call goes.
 *
 * Only the two fields a step needs: `name` for the label and `url` for the logo.
 */
export interface McpServerRef {
  name: string;
  url: string;
}

/**
 * The prefix a server's tools carry, mirroring `app/agents/mcp.py::_tool_prefix`.
 *
 * The backend prefixes every MCP tool with its connection's name so two servers
 * exposing `create_issue` cannot collide, and that prefix is the only trace of where
 * a tool came from that reaches this side: a tool call arrives as a name and
 * arguments, with no provenance on it. So the rule is duplicated here on purpose,
 * and it must stay identical - the cost of drift is a step reading
 * "Github Work Create Issue" instead of "GitHub · Create issue", which is the
 * behaviour with no match at all.
 */
export function mcpToolPrefix(connectionName: string): string {
  return (
    connectionName
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, "_")
      .replace(/^_+|_+$/g, "") || "mcp"
  );
}

export interface McpCall {
  server: string;
  /** The tool as the server named it, without the connection prefix. */
  action: string;
  /** Host of the server's URL, which is what picks its logo. Null if unparsable. */
  domain: string | null;
}

/**
 * Which MCP server a tool call came from, if any of these did.
 *
 * Longest prefix first, because connection names nest: "github" and "github_work"
 * both match `github_work_create_issue`, and only the longer one is right.
 */
export function mcpCall(toolName: string, servers: readonly McpServerRef[]): McpCall | null {
  const matches = servers
    .map((server) => ({ server, prefix: `${mcpToolPrefix(server.name)}_` }))
    .filter(({ prefix }) => toolName.startsWith(prefix) && toolName.length > prefix.length)
    .sort((left, right) => right.prefix.length - left.prefix.length);
  const best = matches[0];
  if (best === undefined) return null;
  return {
    server: best.server.name,
    action: toolName.slice(best.prefix.length),
    domain: hostOf(best.server.url),
  };
}

function hostOf(url: string): string | null {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

/** "create_issue" -> "Create issue": a sentence, not a title. */
function sentence(value: string): string {
  const words = value.split("_").filter(Boolean).join(" ");
  return words === "" ? value : words.charAt(0).toUpperCase() + words.slice(1);
}

/** Words, title-cased: a tool's name, a skill's name, anything snake_cased. */
export function titleWords(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * The line for one tool call.
 *
 * `finished` rather than a status, because the two states a label distinguishes are
 * "still going" and "over" - an error and a refusal are over, and their own markers
 * say which, so a third tense would be a sentence nobody needs.
 */
export function toolStep(
  name: string,
  args: Record<string, unknown> | undefined,
  finished: boolean,
  t: Translate,
  servers: readonly McpServerRef[] = [],
): ToolStep {
  const fromMcp = mcpCall(name, servers);
  if (fromMcp !== null) {
    // The server, then what was asked of it. Named this way round because the
    // server is what somebody is deciding to trust: "Linear · Create issue" says
    // where the side effect landed, and `linear_create_issue` says it in a way
    // nobody reads.
    return {
      label: `${fromMcp.server} · ${sentence(fromMcp.action)}`,
      detail: null,
      kind: "mcp",
      logoDomain: fromMcp.domain,
    };
  }
  const entry = toolEntry(name);
  const kind = entry?.kind ?? "tool";
  const verbs = entry?.verbs;
  if (verbs === undefined) {
    // Everything not from the workspace toolset keeps the captions it had: present
    // tense while running, and what happened once it has.
    return {
      label: finished ? finishedLabel(name, args, t) : toolCaption(name, t),
      detail: subjectOf(name, args, t),
      kind,
    };
  }

  // The whole sentence comes from one message per tense, which selects on whether the
  // call named a subject. A verb interpolated into `{verb} {subject}` would be the
  // `{noun}` defect under another name (#362).
  const named = subjectOf(name, args, t);
  return {
    label: t(finished ? verbs.done : verbs.now, {
      named: named === null ? "no" : "yes",
      subject: named ?? "",
    }),
    detail: null,
    kind,
  };
}

/**
 * What a finished call is called, when the tool's own name is not the useful answer.
 *
 * A loaded skill is the clearest case: the step that matters says *Refund Policy*, not
 * *Load Skill* - which skill it was is the whole content of the step.
 */
function finishedLabel(
  name: string,
  args: Record<string, unknown> | undefined,
  t: Translate,
): string {
  if (name === "load_skill") {
    const skill = text((args ?? {}).skill_name);
    if (skill !== null) return titleWords(skill);
  }
  return toolDisplayName(name, t);
}

/**
 * The one thing a call is about: a file's name, a pattern, a command, a query.
 *
 * The *name* rather than the whole path, because a step is a line in a narration and
 * `/workspace/skills/review/SKILL.md` is not a line. The whole path is in the detail
 * the step opens, where there is room for it.
 */
function subjectOf(
  name: string,
  args: Record<string, unknown> | undefined,
  t: Translate,
): string | null {
  const given = args ?? {};
  if (name === "execute") return text(given.command) ?? text(given.cmd);
  if (name === "grep" || name === "glob") {
    const pattern = text(given.pattern);
    const where = pathArg(given);
    if (pattern === null) return null;
    return where === null ? pattern : t("patternInFile", { pattern, file: basename(where) });
  }
  const path = pathArg(given);
  if (path !== null) return name === "ls" ? path : basename(path);
  return text(given.query) ?? text(given.url) ?? text(given.skill_name);
}
