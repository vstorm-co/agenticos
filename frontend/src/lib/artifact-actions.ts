import type { ArtifactActionField, ArtifactActionRun, ArtifactActionView } from "@/types/artifact";

/** What the platform script inside a page posts to ask for an action. */
export const RUN_REQUEST = "agenticos:run";

/** What the console posts back about a request: a rejection or a state of its run. */
export const RUN_EVENT = "agenticos:run-event";

/** The longest id and action name a request may carry; a longer one is not the page's own script. */
const MAX_TEXT = 200;

/** A request as the page made it. Nothing in it is trusted until it is resolved. */
export interface RunRequest {
  /** The page's own id for this call, echoed in every event about it. */
  id: string;
  /** A workflow id, or the name or label of one of the page's declared actions. */
  action: string;
  input: Record<string, unknown>;
}

/**
 * The request a message from this frame makes, or null for anything else.
 *
 * Only the frame's own window counts - any other frame on the page can post a
 * message too - and only under the nonce the server minted for this load of it:
 * the document of the version shown before, still answering as the frame swaps,
 * posts another. Anything not shaped exactly like a request is dropped without
 * an answer, so nothing a stranger posts is ever echoed back.
 */
export function runRequestFrom(
  event: MessageEvent,
  frame: HTMLIFrameElement | null,
  nonce: string,
): RunRequest | null {
  if (frame === null || nonce === "" || event.source !== frame.contentWindow) return null;
  const data: unknown = event.data;
  if (typeof data !== "object" || data === null) return null;
  const { type, n, id, action, input } = data as Record<string, unknown>;
  if (type !== RUN_REQUEST || n !== nonce) return null;
  if (typeof id !== "string" || id === "" || id.length > MAX_TEXT) return null;
  if (typeof action !== "string" || action === "" || action.length > MAX_TEXT) return null;
  if (typeof input !== "object" || input === null || Array.isArray(input)) return null;
  return { id, action, input: input as Record<string, unknown> };
}

/**
 * The declared action a page's request names, or null.
 *
 * Tried in this order, each on its own: the workflow id (exact, which is what a
 * page should use), then the page's own label, then the workflow's name - the
 * latter two trimmed and compared without regard to case. A tier that matches
 * more than one action is ambiguous and matches none; the next tier is not
 * tried, so a label can never shadow an id. Only ever one of `actions`, which
 * the server listed for this viewer and this version.
 */
export function resolveAction(
  actions: readonly ArtifactActionView[],
  requested: string,
): ArtifactActionView | null {
  const asked = requested.trim().toLowerCase();
  const loose = (word: string) => word.trim().toLowerCase() === asked;
  const tiers: ((action: ArtifactActionView) => boolean)[] = [
    (action) => action.workflow_id === requested,
    (action) => loose(action.label),
    (action) => loose(action.name),
  ];
  for (const matches of tiers) {
    const found = actions.filter(matches);
    if (found.length > 0) return found.length === 1 ? found[0]! : null;
  }
  return null;
}

/** Why one value does not fit the field it was given for. */
export type ProblemKind =
  "required" | "unknown" | "text" | "number" | "integer" | "boolean" | "date" | "choice";

export interface InputProblem {
  /** The field's name, as the workflow declares it. */
  field: string;
  kind: ProblemKind;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

function fits(field: ArtifactActionField, value: unknown): ProblemKind | null {
  switch (field.type) {
    case "text":
      return typeof value === "string" ? null : "text";
    case "number":
      return typeof value === "number" && Number.isFinite(value) ? null : "number";
    case "integer":
      return typeof value === "number" && Number.isInteger(value) ? null : "integer";
    case "boolean":
      return typeof value === "boolean" ? null : "boolean";
    case "date":
      return typeof value === "string" &&
        ISO_DATE.test(value) &&
        !Number.isNaN(Date.parse(`${value}T00:00:00Z`))
        ? null
        : "date";
    case "choice":
      return typeof value === "string" && field.options.includes(value) ? null : "choice";
  }
}

/**
 * What is wrong with `input` against the fields the workflow declares, in the
 * order the fields are declared and then the stray keys. Empty means it may
 * start. Mirrors what the server will check, so a refusal is read before a run
 * is started rather than after.
 */
export function inputProblems(
  fields: readonly ArtifactActionField[],
  input: Record<string, unknown>,
): InputProblem[] {
  const problems: InputProblem[] = [];
  for (const field of fields) {
    const given = Object.hasOwn(input, field.name) ? input[field.name] : undefined;
    if (given === undefined || given === null) {
      if (field.required) problems.push({ field: field.name, kind: "required" });
      continue;
    }
    const kind = fits(field, given);
    if (kind !== null) problems.push({ field: field.name, kind });
    else if (field.required && field.type === "text" && given === "") {
      problems.push({ field: field.name, kind: "required" });
    }
  }
  const declared = new Set(fields.map((field) => field.name));
  for (const key of Object.keys(input)) {
    if (!declared.has(key)) problems.push({ field: key, kind: "unknown" });
  }
  return problems;
}

/**
 * Control and format characters (Cc, Cf) other than a newline and a tab: the
 * ones that draw nothing or reorder what is around them, such as U+202E or a
 * zero-width space.
 */
const HIDDEN = /(?![\n\t])[\p{Cc}\p{Cf}]/gu;

/**
 * A value as the person reads it in the dialog: in full, as text, with every
 * character that would draw nothing or reorder the text around it written out
 * as `\u{202E}`.
 */
export function showValue(value: unknown): string {
  const text = typeof value === "string" ? value : (JSON.stringify(value) ?? String(value));
  return text.replace(
    HIDDEN,
    (char) => `\\u{${(char.codePointAt(0) ?? 0).toString(16).toUpperCase()}}`,
  );
}

/**
 * Why the console refused a request, as the page reads it - a short code, not a
 * sentence: the page words its own message, and the console's own copy is for
 * the person.
 */
export type RejectReason =
  | "cancelled"
  | "busy"
  | "too_many_cancels"
  | "not_ready"
  | "unknown_action"
  | "invalid_input"
  | "rate_limited"
  | "not_found"
  | "unavailable"
  | "failed"
  | "page_changed";

/** The event that rejects a request. */
export function rejection(
  nonce: string,
  id: string,
  reason: RejectReason,
  problems?: readonly InputProblem[],
) {
  return {
    type: RUN_EVENT,
    n: nonce,
    id,
    event: "rejected",
    reason,
    ...(problems === undefined ? {} : { problems }),
  };
}

/** The event that says how a request's run stands. `finished` settles the page's promise. */
export function progress(nonce: string, id: string, run: ArtifactActionRun) {
  return {
    type: RUN_EVENT,
    n: nonce,
    id,
    event: "progress",
    status: run.status,
    finished: run.finished,
    paused: run.paused,
    run_path: run.run_path,
    output_text: run.output_text,
    output_structured: run.output_structured,
    error_message: run.error_message,
  };
}

/**
 * The event for a run the console stopped following while it was paused: the last
 * projection, with `settled` so the page's promise resolves with `paused: true`
 * and `finished: false` instead of never settling.
 */
export function settledRun(nonce: string, id: string, run: ArtifactActionRun) {
  return { ...progress(nonce, id, run), settled: true };
}

/** A run that was just started: nothing to read yet. */
export function startedRun(status: string): ArtifactActionRun {
  return {
    status,
    finished: false,
    paused: false,
    run_path: null,
    output_text: null,
    output_structured: null,
    error_message: null,
  };
}

/** Where a paused run is opened, only ever a console path - never an address a run could name. */
export function consolePath(path: string | null): string | null {
  return path !== null && /^\/workflows\/[\w-]+\/runs\/[\w-]+(\?[\w=&-]*)?$/.test(path)
    ? path
    : null;
}

/** Whether two reads of a run say the same thing to the page. */
export function sameRun(a: ArtifactActionRun | null, b: ArtifactActionRun): boolean {
  return a !== null && JSON.stringify(a) === JSON.stringify(b);
}
