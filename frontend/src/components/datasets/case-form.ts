import type { CaseCheck, DatasetCaseContent, ToolOrderMode } from "@/types/datasets";

/** One earlier turn of the conversation the case continues. */
export interface TurnDraft {
  role: "user" | "assistant";
  content: string;
}

/** One argument a call must carry: its name, and its value as the editor shows it. */
export interface ArgDraft {
  key: string;
  value: string;
}

/** One expected tool call: the tool's name, and the arguments that must match. */
export interface CallDraft {
  tool: string;
  args: ArgDraft[];
}

/**
 * An argument's value as written: plain text stays a string, and anything that
 * reads as JSON - a number, `true`, a list, a quoted string - is that value.
 */
export function argValue(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** The text that reads back as `value` through `argValue`. */
export function argText(value: unknown): string {
  return typeof value === "string" && argValue(value) === value ? value : JSON.stringify(value);
}

/**
 * One check: its type, its main parameter as the editor shows it, and whatever
 * else the stored check carries - a `path`, `case_sensitive` - kept as it was.
 * A check of a type this build does not know keeps everything in `rest`.
 */
export interface CheckDraft {
  type: string;
  value: string;
  rest: Record<string, unknown>;
}

/** A case as the editor holds it: the text fields as strings, the lists as rows. */
export interface CaseDraft {
  input: string;
  reference_answer: string;
  counter_example: string;
  note: string;
  tags: string;
  history: TurnDraft[];
  expected_tool_calls: CallDraft[];
  order_mode: ToolOrderMode;
  checks: CheckDraft[];
}

/** The fields an edit can be refused on, as the form and the server both name them. */
export const CASE_FIELDS = [
  "input",
  "reference_answer",
  "counter_example",
  "note",
  "tags",
  "history",
  "expected_tool_calls",
  "checks",
] as const;

export type CaseField = (typeof CASE_FIELDS)[number];

/** How each check type's main parameter is written: as text, a number, or a JSON object. */
export const CHECK_KINDS = {
  contains: { key: "value", as: "text" },
  not_contains: { key: "value", as: "text" },
  equals: { key: "value", as: "text" },
  regex: { key: "value", as: "text" },
  json_schema: { key: "schema", as: "json" },
  max_cost_usd: { key: "value", as: "number" },
  max_latency_ms: { key: "value", as: "number" },
  judge: { key: "criterion", as: "text" },
} as const;

export type CheckType = keyof typeof CHECK_KINDS;

export const CHECK_TYPES = Object.keys(CHECK_KINDS) as CheckType[];

export function isKnownCheck(type: string): type is CheckType {
  return type in CHECK_KINDS;
}

export const EMPTY_DRAFT: CaseDraft = {
  input: "",
  reference_answer: "",
  counter_example: "",
  note: "",
  tags: "",
  history: [],
  expected_tool_calls: [],
  order_mode: "any",
  checks: [],
};

export function checkDraft(check: CaseCheck): CheckDraft {
  const { type, ...given } = check;
  if (!isKnownCheck(type)) return { type, value: "", rest: given };
  const { key, as } = CHECK_KINDS[type];
  const { [key]: main, ...rest } = given;
  const value = main === undefined ? "" : as === "json" ? JSON.stringify(main) : String(main);
  return { type, value, rest };
}

export function draftOf(content: DatasetCaseContent): CaseDraft {
  return {
    input: content.input,
    reference_answer: content.reference_answer ?? "",
    counter_example: content.counter_example ?? "",
    note: content.note ?? "",
    tags: content.tags.join(", "),
    history: content.history.map(({ role, content: text }) => ({ role, content: text })),
    expected_tool_calls: content.expected_tool_calls.map(({ tool, args }) => ({
      tool,
      args: Object.entries(args).map(([key, value]) => ({ key, value: argText(value) })),
    })),
    order_mode: content.order_mode,
    checks: content.checks.map(checkDraft),
  };
}

/**
 * Whether the draft says what its answer is tested against. The server refuses a
 * case that does not, naming `reference_answer`; this is that rule, read early so
 * the form can say what is missing before anything is sent. A row left blank
 * counts as nothing, as it is not sent.
 */
export function expectsSomething(draft: CaseDraft): boolean {
  return (
    draft.reference_answer.trim() !== "" ||
    draft.counter_example.trim() !== "" ||
    draft.expected_tool_calls.some((call) => call.tool.trim() !== "") ||
    draft.checks.length > 0
  );
}

/** What went wrong reading a draft: the field, and the catalog key saying how. */
export type DraftProblem = {
  field: CaseField;
  key: "schemaNotObject" | "notNumber" | "checkEmpty";
};

function asObject(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function checkOf(check: CheckDraft): CaseCheck | DraftProblem["key"] {
  if (!isKnownCheck(check.type)) return { type: check.type, ...check.rest };
  const { key, as } = CHECK_KINDS[check.type];
  const text = check.value.trim();
  if (text === "") return "checkEmpty";
  if (as === "number") {
    const number = Number(text);
    return Number.isFinite(number)
      ? { type: check.type, ...check.rest, [key]: number }
      : "notNumber";
  }
  if (as === "json") {
    const schema = asObject(text);
    return schema === null ? "schemaNotObject" : { type: check.type, ...check.rest, [key]: schema };
  }
  return { type: check.type, ...check.rest, [key]: check.value };
}

/** Checks as the API takes them, and why any of them cannot be read. */
export function checksOf(drafts: CheckDraft[]): {
  checks: CaseCheck[];
  problems: DraftProblem["key"][];
} {
  const checks: CaseCheck[] = [];
  const problems: DraftProblem["key"][] = [];
  for (const draft of drafts) {
    const read = checkOf(draft);
    if (typeof read === "string") problems.push(read);
    else checks.push(read);
  }
  return { checks, problems };
}

/**
 * The draft as the content the API takes, or the fields it cannot be read on.
 *
 * Blank turns and calls with no tool are left out, as rows added and never
 * filled. Only the shape is checked here; what each entry must hold is the
 * server's to say, and it names the field when it refuses.
 */
export function contentOf(
  draft: CaseDraft,
): { content: DatasetCaseContent; problems: [] } | { content: null; problems: DraftProblem[] } {
  const problems: DraftProblem[] = [];
  const calls: DatasetCaseContent["expected_tool_calls"] = [];
  for (const call of draft.expected_tool_calls) {
    if (call.tool.trim() === "") continue;
    const named = call.args.filter((arg) => arg.key.trim() !== "");
    const args = Object.fromEntries(named.map((arg) => [arg.key.trim(), argValue(arg.value)]));
    calls.push({ tool: call.tool.trim(), args });
  }
  const read = checksOf(draft.checks);
  problems.push(...read.problems.map((key) => ({ field: "checks" as const, key })));
  if (problems.length > 0) return { content: null, problems };
  const optional = (text: string) => (text.trim() === "" ? null : text);
  return {
    problems: [],
    content: {
      input: draft.input,
      reference_answer: optional(draft.reference_answer),
      counter_example: optional(draft.counter_example),
      note: optional(draft.note),
      tags: draft.tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      history: draft.history.filter((turn) => turn.content.trim() !== ""),
      expected_tool_calls: calls,
      order_mode: draft.order_mode,
      checks: read.checks,
    },
  };
}
