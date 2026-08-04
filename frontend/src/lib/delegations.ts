/**
 * The frames of a delegation, folded into the panels a reader sees.
 *
 * A pure reducer over an ordered list, kept out of `use-chat.ts` and out of the
 * panel for one reason: the interesting part of streaming a delegation is not the
 * socket and not the markup, it is what three concurrent specialists do to a list.
 * Every rule here is a rule about that, and can be asserted without a hook, a
 * socket or a render - which is why it sits beside `tool-steps.ts` rather than in
 * the component that draws it.
 *
 * The list is ordered by when each delegation started, and it is a list rather
 * than a map because that order is the reading order - a fan-out of three shows
 * in the order the parent asked, not in whichever order a hash lands.
 */

import type { Delegation, DelegationStatus, SubagentFrame, SubagentStartFrame } from "@/types";

/**
 * Which delegation a nested one belongs to.
 *
 * No frame names a parent - the contract carries `depth` and nothing else - so
 * the parent is the most recent delegation one level up that has not finished.
 * That is exactly right for the shape that needs it: a specialist delegates while
 * it is running, so the open delegation above is the one that made the call. It is
 * a heuristic, and it is wrong only in a case nothing can currently produce - two
 * specialists at the same depth whose children arrive interleaved *after* the
 * first has finished - where the nesting misreads and no content is lost.
 */
function parentOf(current: Delegation[], depth: number): string | null {
  if (depth === 0) return null;
  for (let index = current.length - 1; index >= 0; index--) {
    const candidate = current[index]!;
    if (candidate.depth === depth - 1 && candidate.status === "running") return candidate.taskId;
  }
  return null;
}

function started(current: Delegation[], frame: SubagentStartFrame): Delegation[] {
  // A `task_id` is unique per delegation, so a second start for one is a repeat
  // rather than a second delegation - keeping the first preserves whatever has
  // already streamed into it.
  if (current.some((delegation) => delegation.taskId === frame.task_id)) return current;
  return [
    ...current,
    {
      taskId: frame.task_id,
      subagent: frame.subagent,
      depth: frame.depth,
      mode: frame.mode,
      prompt: frame.prompt,
      parentTaskId: parentOf(current, frame.depth),
      status: "running" as DelegationStatus,
      text: "",
      thinking: "",
      steps: [],
      costUsd: null,
      inputTokens: null,
      outputTokens: null,
      error: null,
    },
  ];
}

/** The frame applied to the one delegation it names, everything else untouched. */
function updated(
  current: Delegation[],
  taskId: string,
  change: (delegation: Delegation) => Delegation,
): Delegation[] {
  const index = current.findIndex((delegation) => delegation.taskId === taskId);
  // Dropped rather than turned into a nameless panel. It happens for real: a
  // background delegation from the previous turn can report after the panels were
  // replaced, and a panel built from a text delta has no delegate name, no prompt
  // and no way to ever be closed.
  if (index === -1) return current;
  const next = [...current];
  next[index] = change(current[index]!);
  return next;
}

function withResult(delegation: Delegation, toolCallId: string, ok: boolean): Delegation {
  return {
    ...delegation,
    steps: delegation.steps.map((step) => (step.id === toolCallId ? { ...step, ok } : step)),
  };
}

/**
 * One frame folded into the panels.
 *
 * Returns the same array when a frame changes nothing, so a dropped frame does not
 * cost a render.
 */
export function applyDelegationFrame(current: Delegation[], frame: SubagentFrame): Delegation[] {
  switch (frame.kind) {
    case "subagent_start":
      return started(current, frame);
    case "subagent_text_delta":
      return updated(current, frame.task_id, (delegation) => ({
        ...delegation,
        text: delegation.text + frame.delta,
      }));
    case "subagent_thinking_delta":
      return updated(current, frame.task_id, (delegation) => ({
        ...delegation,
        thinking: delegation.thinking + frame.delta,
      }));
    case "subagent_tool_call":
      return updated(current, frame.task_id, (delegation) =>
        delegation.steps.some((step) => step.id === frame.tool_call_id)
          ? delegation
          : {
              ...delegation,
              steps: [
                ...delegation.steps,
                { id: frame.tool_call_id, name: frame.tool_name, ok: null },
              ],
            },
      );
    case "subagent_tool_result":
      return updated(current, frame.task_id, (delegation) =>
        withResult(delegation, frame.tool_call_id, frame.ok),
      );
    case "subagent_complete":
      return updated(current, frame.task_id, (delegation) => ({
        ...delegation,
        status: frame.status,
        costUsd: frame.cost_usd,
        inputTokens: frame.input_tokens,
        outputTokens: frame.output_tokens,
        error: frame.error,
      }));
  }
}

/**
 * Close whatever is still open, because nothing more is coming.
 *
 * For the two ends a delegation can meet that produce no `subagent_complete` of
 * its own: the person pressed stop, or the turn failed. A panel left running
 * after either spins forever - the state a parked tool call used to sit in.
 *
 * Returns the same array when nothing was open, so an `error` frame on a turn that
 * never delegated costs no render.
 */
export function closeOpenDelegations(current: Delegation[]): Delegation[] {
  if (!current.some((delegation) => delegation.status === "running")) return current;
  return current.map((delegation) =>
    delegation.status === "running"
      ? { ...delegation, status: "cancelled" as DelegationStatus }
      : delegation,
  );
}

/** The delegations started from this one, in the order they started. */
export function childrenOf(current: Delegation[], taskId: string): Delegation[] {
  return current.filter((delegation) => delegation.parentTaskId === taskId);
}

/** The delegations the run's own agent called, as opposed to a specialist's. */
export function rootsOf(current: Delegation[]): Delegation[] {
  return current.filter((delegation) => delegation.parentTaskId === null);
}
