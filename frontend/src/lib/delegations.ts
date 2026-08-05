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
 * Which delegation a nested one belongs to, as its start frame names it.
 *
 * **The frame names it; this never guesses.** It used to: the parent was taken to
 * be the most recent still-running delegation one level up, which is wrong the
 * moment more than one delegation at that level is running - the ordinary fan-out.
 * Two roots, a helper each, and the researcher's helper was drawn inside the
 * writer's panel while the researcher's panel showed no children at all.
 * `SubagentRuntime.depth` is *told* rather than computed precisely so that a
 * surface cannot nest under the wrong parent; the surface then computed the parent
 * anyway. Do not put that back.
 *
 * Two answers are null, and both draw the delegation as a root panel:
 *
 * - **The frame carries no `parent_task_id`.** An older backend, mid-deploy. A
 *   flat list of panels is legible; a confidently wrong tree is not.
 * - **It names a delegation this list does not hold.** The case `updated` below
 *   documents - a background delegation of the previous turn reporting after the
 *   panels were replaced. At the top it is visible; under a parent that is not
 *   there it would stream into nothing anybody can see.
 */
function parentIn(current: Delegation[], named: string | null | undefined): string | null {
  if (named === undefined || named === null) return null;
  return current.some((delegation) => delegation.taskId === named) ? named : null;
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
      parentTaskId: parentIn(current, frame.parent_task_id),
      status: "running" as DelegationStatus,
      text: "",
      thinking: "",
      steps: [],
      runId: null,
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
        // Kept rather than dropped: the delegate's run id is the only thing that
        // ties this panel to the run history entry it produced, and the backend
        // sends it for exactly that. See `runId` on `Delegation`.
        runId: frame.run_id,
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
