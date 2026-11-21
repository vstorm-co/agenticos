import type { MessagePart, ToolCall } from "@/types";
import { toolLookupName } from "./tool-identity";
import { drawnUnderTheAnswer } from "./turn-extras";

/** A late streaming frame cannot reopen a completed invocation or erase its result. */
export function mergeToolCall(previous: ToolCall, incoming: Partial<ToolCall>): ToolCall {
  if (incoming.status === "pending" && previous.status !== "pending") return previous;
  const terminal = previous.status === "completed" || previous.status === "error";
  if (
    terminal &&
    incoming.status &&
    ["pending", "running", "awaiting_answer", "awaiting_approval"].includes(incoming.status)
  )
    return previous;
  return { ...previous, ...incoming, result: incoming.result ?? previous.result };
}

/** Preserve arrival order while repeated frames update a call in place. */
export function canonicalParts(parts: readonly MessagePart[]): MessagePart[] {
  const latest = new Map<string, MessagePart>();
  for (const part of parts) {
    const key =
      part.type === "tool" && part.toolCall ? `tool:${part.toolCall.id}` : `part:${part.id}`;
    const previous = latest.get(key);
    latest.set(
      key,
      previous
        ? {
            ...part,
            id: previous.id,
            ...(part.toolCall && previous.toolCall
              ? { toolCall: mergeToolCall(previous.toolCall, part.toolCall) }
              : {}),
          }
        : part,
    );
  }
  return [...latest.values()];
}

export function isQuestionCall(call: ToolCall): boolean {
  return toolLookupName(call) === "ask_user_question";
}

export function isQuestionRun(run: PartRun): boolean {
  return (
    run.kind === "tools" &&
    run.parts.every((part) => part.toolCall && isQuestionCall(part.toolCall))
  );
}

export type PartRun =
  | {
      kind: "tools";
      /** Never empty: the run exists because a call opened it. */
      parts: [MessagePart, ...MessagePart[]];
      /** Whether this run ends the turn, which is what may still be streaming. */
      isLast: boolean;
    }
  | {
      kind: "other";
      part: MessagePart;
      content: string;
      isLast: boolean;
      questionParts?: MessagePart[];
    };

type WorkPartGroup =
  { kind: "work"; runs: [PartRun, ...PartRun[]] } | { kind: "visible"; run: PartRun };

/** Text, questions and explicit cards break the work rail and keep their position. */
export function groupWorkParts(runs: PartRun[]): WorkPartGroup[] {
  const groups: WorkPartGroup[] = [];
  for (const run of runs) {
    if (isQuestionRun(run) || (run.kind === "other" && run.part.type !== "thinking")) {
      groups.push({ kind: "visible", run });
      continue;
    }
    const previous = groups.at(-1);
    if (previous?.kind === "work") previous.runs.push(run);
    else groups.push({ kind: "work", runs: [run] });
  }
  return groups;
}

/**
 * The turn's parts, with consecutive tool calls gathered into one run.
 *
 * Grouping is what makes the steps read as one thread: the rail they hang from has to
 * be a single element, because a border on each row leaves gaps between them and a
 * dashed line says something this does not mean. A part of any other kind - text, or
 * thinking - closes the run, which is right: the agent said something, so what follows
 * is a new stretch of work.
 *
 * Empty text and thinking parts are dropped rather than rendered as empty bubbles,
 * which is what the flat map did with them.
 */
export function runsOf(parts: MessagePart[]): PartRun[] {
  const runs: PartRun[] = [];
  for (const part of canonicalParts(parts)) {
    if (part.type === "tool" && part.toolCall) {
      // Drawn under the answer instead - buttons, a card - by `TurnExtras`.
      if (drawnUnderTheAnswer(toolLookupName(part.toolCall))) continue;
      const open = runs.at(-1);
      if (open?.kind === "tools" && isQuestionRun(open) === isQuestionCall(part.toolCall))
        open.parts.push(part);
      else runs.push({ kind: "tools", parts: [part], isLast: false });
      continue;
    }
    if (part.type === "ask_user") {
      const previous = runs.at(-1);
      if (previous?.kind === "other" && previous.part.type === "ask_user")
        previous.questionParts?.push(part);
      else runs.push({ kind: "other", part, questionParts: [part], content: "", isLast: false });
      continue;
    }
    if (part.type === "workflow_run" || part.type === "phone_call" || part.type === "model_setup") {
      runs.push({ kind: "other", part, content: "", isLast: false });
      continue;
    }
    if (part.type === "steer" && part.content) {
      runs.push({ kind: "other", part, content: part.content, isLast: false });
      continue;
    }
    if (
      (part.type === "text" || part.type === "thinking") &&
      part.content !== undefined &&
      part.content !== ""
    ) {
      runs.push({ kind: "other", part, content: part.content, isLast: false });
    }
  }
  const last = runs.at(-1);
  if (last !== undefined) last.isLast = true;
  return runs;
}
