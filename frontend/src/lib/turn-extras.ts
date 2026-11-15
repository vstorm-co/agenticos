import { toolLookupName } from "@/lib/tool-identity";
/**
 * What a turn's calls leave under its answer rather than in its steps (#2301):
 * next steps as buttons, a card to switch on a capability the agent lacks, and a
 * line saying what the agent noted about the person.
 *
 * Read off the calls themselves, so a reloaded conversation draws the same
 * things the streamed one did.
 */

import type { ToolCall } from "@/types/chat";
import type { CodingTaskChanges } from "./coding-changes-api";

import { pathArg } from "./tool-steps";
import { toolEntry } from "./tool-catalog";

export const SUGGEST_NEXT_STEPS = "suggest_next_steps";
export const REQUEST_CAPABILITY = "request_capability";
export const PROPOSE_SETUP = "propose_setup";

/** Whether a call is drawn under the answer instead of as a step. */
export function drawnUnderTheAnswer(name: string): boolean {
  return toolEntry(name)?.hidden === true;
}

function finished(calls: readonly ToolCall[] | undefined, name: string): ToolCall[] {
  return (calls ?? []).filter(
    (call) => toolLookupName(call) === name && call.status === "completed",
  );
}

function jsonObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "string") return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/** The steps the turn's last `suggest_next_steps` offered, as the server kept them. */
export function followUpsOf(calls: readonly ToolCall[] | undefined): string[] {
  const last = finished(calls, SUGGEST_NEXT_STEPS).at(-1);
  const steps = jsonObject(last?.result)?.steps;
  return Array.isArray(steps)
    ? steps.filter((step): step is string => typeof step === "string" && step !== "")
    : [];
}

export interface CapabilityCard {
  callId: string;
  agentId: string;
  capabilityId: string;
  name: string;
  reason: string;
}

/** Every capability the turn asked to have switched on, one card each. */
export function capabilityCardsOf(calls: readonly ToolCall[] | undefined): CapabilityCard[] {
  return finished(calls, REQUEST_CAPABILITY).flatMap((call) => {
    const card = jsonObject(call.result);
    const { agent_id, capability_id, name, reason } = card ?? {};
    return typeof agent_id === "string" &&
      typeof capability_id === "string" &&
      typeof name === "string" &&
      typeof reason === "string"
      ? [{ callId: call.id, agentId: agent_id, capabilityId: capability_id, name, reason }]
      : [];
  });
}

export interface MemoryChange {
  callId: string;
  forgot: boolean;
  /** The note as the agent described it, else its name. */
  label: string;
}

const SAVES = new Set(["write_memory", "edit_memory"]);

/** What the turn noted down about the person, or forgot - each change once. */
export type SetupKind = "agent" | "routine" | "watch" | "connection";

export interface SetupProposal {
  key: string;
  kind: SetupKind;
  title: string;
  why: string;
  /** What the agent should do, the routine's prompt, or the service's name. */
  request: string;
  cron: string | null;
  /** A connection's catalog key, which the card resolves to a logo and a one-click connect. */
  server: string | null;
}

const SETUP_KINDS: readonly string[] = ["agent", "routine", "watch", "connection"];

/** What the turn's last `propose_setup` proposed, one card each. */
export function setupProposalsOf(calls: readonly ToolCall[] | undefined): SetupProposal[] {
  const last = finished(calls, PROPOSE_SETUP).at(-1);
  const proposals = jsonObject(last?.result)?.proposals;
  if (!last || !Array.isArray(proposals)) return [];
  return proposals.flatMap((proposal: unknown, index) => {
    if (!proposal || typeof proposal !== "object") return [];
    const { kind, title, why, request, cron, server } = proposal as Record<string, unknown>;
    return typeof kind === "string" &&
      SETUP_KINDS.includes(kind) &&
      typeof title === "string" &&
      typeof why === "string" &&
      typeof request === "string"
      ? [
          {
            key: `${last.id}-${index}`,
            kind: kind as SetupKind,
            title,
            why,
            request,
            cron: typeof cron === "string" ? cron : null,
            server: typeof server === "string" && server ? server : null,
          },
        ]
      : [];
  });
}

/** A completed call can still be a refusal, so require the runtime's confirmation. */
export function recordedMemoryStatement(call: ToolCall): string | null {
  if (
    call.status !== "completed" ||
    !["remember", "correct_memory"].includes(toolLookupName(call)) ||
    typeof call.result !== "string" ||
    !/^(Recorded|Corrected) \(claim [0-9a-f-]{36}\)/i.test(call.result)
  )
    return null;
  return typeof call.args.statement === "string" ? call.args.statement : null;
}

export function memoryChangesOf(calls: readonly ToolCall[] | undefined): MemoryChange[] {
  return (calls ?? []).flatMap((call) => {
    const statement = recordedMemoryStatement(call);
    if (statement) return [{ callId: call.id, forgot: false, label: statement }];
    const forgot = toolLookupName(call) === "delete_memory";
    if (call.status !== "completed" || !(forgot || SAVES.has(toolLookupName(call)))) return [];
    if (
      typeof call.result !== "string" ||
      !/^(Saved|Updated|Forgot) note ['"][\s\S]+['"]\.$/.test(call.result)
    )
      return [];
    const { name, description } = call.args;
    // The index the agent keeps for itself is not a note about anybody.
    if (name === "MEMORY.md") return [];
    const label = typeof description === "string" && description ? description : name;
    return typeof label === "string" && label ? [{ callId: call.id, forgot, label }] : [];
  });
}

/** Files the turn's successful writes or coding harness reported changing. */
export function codingChangeIdsOf(calls: readonly ToolCall[] | undefined): string[] {
  return [
    ...new Set(
      finished(calls, "run_coding_agent").flatMap((call) => {
        const id = jsonObject(call.result)?.changes_id;
        return typeof id === "string" ? [id] : [];
      }),
    ),
  ];
}

export function filesChangedOf(
  calls: readonly ToolCall[] | undefined,
  changeSets: ReadonlyMap<string, CodingTaskChanges> = new Map(),
): string[] {
  const paths = new Set<string>();
  for (const call of calls ?? []) {
    if (call.status !== "completed") continue;
    if (toolLookupName(call) === "write_file" || toolLookupName(call) === "edit_file") {
      const path = pathArg(call.args);
      if (path) paths.add(path);
    } else if (toolLookupName(call) === "run_coding_agent") {
      const report = jsonObject(call.result);
      if (typeof report?.changes_id === "string") {
        for (const file of changeSets.get(report.changes_id)?.files ?? []) paths.add(file.path);
        continue;
      }
      const files = report?.files_changed;
      if (Array.isArray(files))
        for (const path of files) if (typeof path === "string" && path.trim()) paths.add(path);
    }
  }
  return [...paths];
}
