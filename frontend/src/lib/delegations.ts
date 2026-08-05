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

import { ApiError } from "@/lib/api-error";
import type { Delegation, DelegationStatus, SubagentFrame, SubagentStartFrame } from "@/types";
import type { RunStatus } from "@/types/runs";

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
  // already streamed into it. The one repeat that is not a no-op is a resume: a
  // delegation that parked for a person is continued under the same id, so its
  // panel goes back to running rather than staying on "waiting for a person".
  const existing = current.find((delegation) => delegation.taskId === frame.task_id);
  if (existing) {
    return existing.status === "awaiting_approval"
      ? updated(current, frame.task_id, (delegation) => ({
          ...delegation,
          status: "running" as DelegationStatus,
        }))
      : current;
  }
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
    case "subagent_awaiting_approval":
      // The delegate stopped for a person. Close the panel with a state that says
      // so, rather than leaving it reading "working" for the length of the wait -
      // and never, if nobody decides. No cost and no run id: the continuation
      // records the outcome when the person decides.
      return updated(current, frame.task_id, (delegation) => ({
        ...delegation,
        status: "awaiting_approval" as DelegationStatus,
      }));
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

/**
 * A resumed run's terminal status, as the disposition its parked panels take.
 *
 * `running` and `awaiting_approval` are absent on purpose: neither is terminal, so
 * a panel waiting on a person stays waiting (`resolveAwaitingOnResume`). A run has
 * no `budget_exceeded` counterpart on a delegation panel, so it reads as `failed` -
 * the delegate stopped without finishing, which is what `failed` says.
 */
const TERMINAL_DELEGATION_STATUS: Partial<Record<RunStatus, DelegationStatus>> = {
  completed: "completed",
  failed: "failed",
  cancelled: "cancelled",
  budget_exceeded: "failed",
};

/**
 * Move panels waiting on a person to the outcome of the run that has now resumed.
 *
 * A sync delegate that parks on an approval leaves its panel `awaiting_approval`,
 * and in web chat the resume that follows the decision runs over HTTP
 * (`POST /runs/{id}/resume`), not over the socket this conversation streams. So no
 * `subagent_complete` reaches `applyDelegationFrame`, and without this the panel
 * reads "waiting for approval" forever - the resumed answer appears above a
 * delegation that never leaves the waiting state (agenticos#173). This supplies the
 * closing the socket did not: the resumed run's own status is the only per-delegation
 * outcome available over HTTP, so every panel still waiting takes it.
 *
 * A resume that parks *again* (`awaiting_approval`, or a run still `running`) is not
 * terminal and changes nothing: the delegate is waiting on a fresh decision, and
 * closing its panel would claim an outcome that has not happened. Cost, tokens and
 * the run id stay as they were - the frame that carries them never came, and
 * inventing them is worse than leaving them null.
 *
 * Returns the same array when nothing waits or the run has not settled, so a resume
 * with no delegation in it costs no render.
 */
export function resolveAwaitingOnResume(current: Delegation[], runStatus: RunStatus): Delegation[] {
  const resolved = TERMINAL_DELEGATION_STATUS[runStatus];
  if (resolved === undefined) return current;
  if (!current.some((delegation) => delegation.status === "awaiting_approval")) return current;
  return current.map((delegation) =>
    delegation.status === "awaiting_approval" ? { ...delegation, status: resolved } : delegation,
  );
}

/**
 * The terminal run status a *failed* resume reports, or null when it reports none.
 *
 * `POST /runs/{id}/resume` answers with the run's status when it returns - and the
 * caller reconciles its panels from that (`resolveAwaitingOnResume`). When the
 * continuation *raises*, there is no answer: the backend records the run terminal,
 * commits it, and re-raises carrying that status in the error envelope's
 * `details.status` (code `RUN_EXECUTION_FAILED`). This reads it back so the same
 * reconciliation runs on the error path, closing a panel the raising resume would
 * otherwise leave waiting forever (agenticos#262).
 *
 * Only a genuinely terminal status counts. A resume that could not be *built* - a
 * secret deleted since the park, a model profile removed - leaves the run still
 * parked and carries no status here; that returns null, and the caller restores the
 * decision for a retry that can now succeed. `running` and `awaiting_approval`
 * likewise return null: neither is an outcome to close a panel to.
 */
export function resumeFailureStatus(error: unknown): RunStatus | null {
  if (!(error instanceof ApiError)) return null;
  const status = error.details?.status;
  return typeof status === "string" && status in TERMINAL_DELEGATION_STATUS
    ? (status as RunStatus)
    : null;
}

/** The delegations started from this one, in the order they started. */
export function childrenOf(current: Delegation[], taskId: string): Delegation[] {
  return current.filter((delegation) => delegation.parentTaskId === taskId);
}

/** The delegations the run's own agent called, as opposed to a specialist's. */
export function rootsOf(current: Delegation[]): Delegation[] {
  return current.filter((delegation) => delegation.parentTaskId === null);
}
