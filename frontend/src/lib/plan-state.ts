/**
 * The agent's own checklist, read back out of the calls it made to keep it.
 *
 * The plan lives in the run's `PlanStore` on the backend and reaches this side only
 * as tool text: `write_plan` and `read_plan` answer with the whole checklist, and
 * the granular tools answer with one line about one step. Nothing streams a plan
 * frame - `todo_event` is in `WSEventType` as a frame no surface has ever emitted -
 * so a surface that wants the plan as it now stands folds those results in order.
 *
 * Which is what this module is: a parser for the two rendered shapes, and a fold
 * over a turn's calls. Parsing prose is a poor foundation, and it is the only one
 * there is until the runner emits the store; keep the shapes in one place so the
 * day it does, one module changes.
 *
 * The glyphs are `_ICONS` in `pydantic_ai_harness.planning._toolset`, and the two
 * line shapes are its `render_plan` (`1. [x] content`) and `render_flat`
 * (`1. [x] [a1b2c3d4] content`).
 */

import type { ChatMessage, ToolCall } from "@/types";

export type PlanStepStatus = "pending" | "in_progress" | "completed" | "cancelled" | "blocked";

export interface PlanStep {
  /** The step's id, where the line that named it carried one. */
  id: string | null;
  content: string;
  status: PlanStepStatus;
}

export interface PlanProgress {
  steps: readonly PlanStep[];
  completed: number;
  total: number;
  /** Completed share of the plan, 0-100, for the bar. */
  percent: number;
  /** The step being worked on, which is what a collapsed strip says. */
  active: PlanStep | null;
  /** Whether every step is finished one way or another. */
  finished: boolean;
}

/** The tools whose results this module reads. Nothing else touches the plan. */
const PLANNING_TOOLS = new Set([
  "write_plan",
  "read_plan",
  "add_task",
  "update_task_status",
  "update_task_statuses",
  "remove_task",
  "add_subtask",
  "set_dependency",
  "get_available_tasks",
]);

const STATUS_BY_GLYPH: Record<string, PlanStepStatus> = {
  " ": "pending",
  "~": "in_progress",
  x: "completed",
  "-": "cancelled",
  "!": "blocked",
};

const STATUS_NAMES = new Set<string>([
  "pending",
  "in_progress",
  "completed",
  "cancelled",
  "blocked",
]);

/** `1. [x] content`, or `1. [x] [a1b2c3d4] content` where the renderer had ids. */
const STEP_LINE = /^\s*\d+\.\s+\[(.)\]\s+(?:\[([0-9a-z]+)\]\s+)?(.*\S)\s*$/;

/** `Updated step 'Ship it' status to 'completed'.` */
const ONE_STATUS = /^Updated step '(.+)' status to '(\w+)'\.$/;

/** One line of a batch update: `- [a1b2c3d4] Ship it -> completed`. */
const BATCH_STATUS = /^-\s+\[([0-9a-z]+)\]\s+(.+?)\s+->\s+(\w+)$/;

/** `Added step 'Ship it' with id: a1b2c3d4` */
const ADDED_STEP = /^Added step '(.+)' with id: ([0-9a-z]+)$/;

function isStatus(name: string): name is PlanStepStatus {
  return STATUS_NAMES.has(name);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/**
 * A capture group the pattern that matched makes mandatory.
 *
 * Every pattern above brackets its content and status groups without `?`, so a
 * match means the group is there. The fallback exists because
 * `noUncheckedIndexedAccess` cannot see that, and nothing reaches it.
 */
function required(match: RegExpExecArray, index: number): string {
  /* v8 ignore next -- the patterns above make these groups mandatory */
  return match[index] ?? "";
}

/**
 * The checklist a rendered plan holds, or null for text that carries none.
 *
 * Null rather than an empty plan on purpose: `No plan yet.` and a refused write
 * (`Plan not updated: …`) both mean "the plan is whatever it already was", and a
 * fold that treated them as an empty checklist would erase a plan on a typo.
 */
export function parsePlan(text: string): PlanStep[] | null {
  const steps: PlanStep[] = [];
  for (const line of text.split("\n")) {
    const match = STEP_LINE.exec(line);
    if (match === null) continue;
    const status = STATUS_BY_GLYPH[required(match, 1)];
    if (status === undefined) continue;
    steps.push({ id: match[2] ?? null, content: required(match, 3), status });
  }
  return steps.length > 0 ? steps : null;
}

/** The steps `write_plan` was called with, for a call whose result has not landed. */
function stepsFromArgs(args: Record<string, unknown>): PlanStep[] | null {
  const items = args.items;
  if (!Array.isArray(items)) return null;
  const steps: PlanStep[] = [];
  for (const row of items) {
    if (!isRecord(row) || typeof row.content !== "string") continue;
    const status = typeof row.status === "string" && isStatus(row.status) ? row.status : "pending";
    steps.push({ id: typeof row.id === "string" ? row.id : null, content: row.content, status });
  }
  return steps.length > 0 ? steps : null;
}

function resultText(call: ToolCall): string {
  if (typeof call.result === "string") return call.result;
  return call.result === undefined ? "" : JSON.stringify(call.result);
}

function withStatus(
  steps: readonly PlanStep[],
  match: (step: PlanStep) => boolean,
  status: PlanStepStatus,
): readonly PlanStep[] {
  return steps.map((step) => (match(step) ? { ...step, status } : step));
}

/**
 * The plan after one planning call, given the plan before it.
 *
 * A whole-plan answer replaces the checklist; a one-line answer amends the step it
 * names. Amending by *content* is what the one-step tools leave possible - their
 * confirmation quotes the content and not always the id - and it is why a step's
 * text is treated as its name here.
 */
function fold(steps: readonly PlanStep[], call: ToolCall): readonly PlanStep[] {
  const text = resultText(call);
  const whole = parsePlan(text);
  if (whole !== null) return whole;

  // A call still in flight, or one whose result was never written down. Its
  // arguments are the plan it is in the middle of writing, which is what makes the
  // strip appear as the agent plans rather than a turn later.
  if (text === "" && call.name === "write_plan") return stepsFromArgs(call.args) ?? steps;

  const one = ONE_STATUS.exec(text);
  if (one !== null) {
    const status = required(one, 2);
    return isStatus(status) ? withStatus(steps, (step) => step.content === one[1], status) : steps;
  }

  const added = ADDED_STEP.exec(text);
  if (added !== null) {
    return [...steps, { id: required(added, 2), content: required(added, 1), status: "pending" }];
  }

  let next = steps;
  for (const line of text.split("\n")) {
    const batch = BATCH_STATUS.exec(line);
    if (batch === null) continue;
    const status = required(batch, 3);
    if (!isStatus(status)) continue;
    next = withStatus(next, (step) => step.id === batch[1] || step.content === batch[2], status);
  }
  return next;
}

/** Every planning call in a conversation, in the order they were made. */
function planningCalls(messages: readonly ChatMessage[]): ToolCall[] {
  const calls: ToolCall[] = [];
  for (const message of messages) {
    const parts = message.parts ?? [];
    const fromParts = parts.flatMap((part) => (part.toolCall ? [part.toolCall] : []));
    // A replayed turn carries its calls in `parts`; a live one is assembled into
    // both, so reading each is one call twice. Parts win where a turn has them.
    for (const call of fromParts.length > 0 ? fromParts : (message.toolCalls ?? [])) {
      if (PLANNING_TOOLS.has(call.name)) calls.push(call);
    }
  }
  return calls;
}

/** What a checklist adds up to: the counts, the bar's width, the step in flight. */
export function progressOf(steps: readonly PlanStep[]): PlanProgress {
  const completed = steps.filter((step) => step.status === "completed").length;
  const settled = steps.filter(
    (step) => step.status === "completed" || step.status === "cancelled",
  ).length;
  return {
    steps,
    completed,
    total: steps.length,
    percent: steps.length === 0 ? 0 : Math.round((completed / steps.length) * 100),
    active: steps.find((step) => step.status === "in_progress") ?? null,
    finished: steps.length > 0 && settled === steps.length,
  };
}

/**
 * The plan as this conversation now stands, or null where nothing planned.
 *
 * Folded over the whole transcript rather than read off the last call, because the
 * last call is usually `update_task_status` and knows one step's worth of the plan.
 */
export function planProgress(messages: readonly ChatMessage[]): PlanProgress | null {
  let steps: readonly PlanStep[] = [];
  for (const call of planningCalls(messages)) steps = fold(steps, call);
  return steps.length === 0 ? null : progressOf(steps);
}
