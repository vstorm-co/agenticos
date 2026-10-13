import type { DatasetCaseContent, ToolOrderMode } from "@/types/datasets";

/**
 * A case as the editor holds it: every field a string a text box can show.
 *
 * The three structured fields - the turns before the input, the expected tool
 * calls and the checks - are edited as JSON, the same text a CSV export holds
 * them as, so what somebody writes here and what they would write in a file
 * are one format.
 */
export interface CaseDraft {
  input: string;
  reference_answer: string;
  counter_example: string;
  note: string;
  tags: string;
  history: string;
  expected_tool_calls: string;
  order_mode: ToolOrderMode;
  checks: string;
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

const JSON_FIELDS = ["history", "expected_tool_calls", "checks"] as const;

function asJson(value: unknown[]): string {
  return value.length === 0 ? "" : JSON.stringify(value, null, 2);
}

export const EMPTY_DRAFT: CaseDraft = {
  input: "",
  reference_answer: "",
  counter_example: "",
  note: "",
  tags: "",
  history: "",
  expected_tool_calls: "",
  order_mode: "any",
  checks: "",
};

export function draftOf(content: DatasetCaseContent): CaseDraft {
  return {
    input: content.input,
    reference_answer: content.reference_answer ?? "",
    counter_example: content.counter_example ?? "",
    note: content.note ?? "",
    tags: content.tags.join(", "),
    history: asJson(content.history),
    expected_tool_calls: asJson(content.expected_tool_calls),
    order_mode: content.order_mode,
    checks: asJson(content.checks),
  };
}

/** What went wrong reading a draft: the field, and the catalog key saying how. */
export type DraftProblem = { field: CaseField; key: "notJson" | "notList" };

/**
 * The draft as the content the API takes, or the fields that are not valid JSON lists.
 *
 * Only the shape is checked here - that a structured field is a list. What each
 * entry must hold is the server's to say, and it names the field when it refuses.
 */
export function contentOf(
  draft: CaseDraft,
): { content: DatasetCaseContent; problems: [] } | { content: null; problems: DraftProblem[] } {
  const problems: DraftProblem[] = [];
  const parsed: Record<(typeof JSON_FIELDS)[number], unknown[]> = {
    history: [],
    expected_tool_calls: [],
    checks: [],
  };
  for (const field of JSON_FIELDS) {
    const text = draft[field].trim();
    if (text === "") continue;
    try {
      const value: unknown = JSON.parse(text);
      if (Array.isArray(value)) parsed[field] = value;
      else problems.push({ field, key: "notList" });
    } catch {
      problems.push({ field, key: "notJson" });
    }
  }
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
      history: parsed.history as DatasetCaseContent["history"],
      expected_tool_calls: parsed.expected_tool_calls as DatasetCaseContent["expected_tool_calls"],
      order_mode: draft.order_mode,
      checks: parsed.checks as DatasetCaseContent["checks"],
    },
  };
}
