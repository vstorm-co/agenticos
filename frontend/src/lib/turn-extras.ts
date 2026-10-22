/**
 * What a turn's calls leave under its answer rather than in its steps (#2301):
 * next steps as buttons, a card to switch on a capability the agent lacks, and a
 * line saying what the agent noted about the person.
 *
 * Read off the calls themselves, so a reloaded conversation draws the same
 * things the streamed one did.
 */

import type { ToolCall } from "@/types/chat";

import { toolEntry } from "./tool-catalog";

export const SUGGEST_NEXT_STEPS = "suggest_next_steps";
export const REQUEST_CAPABILITY = "request_capability";
export const PROPOSE_SETUP = "propose_setup";

/** Whether a call is drawn under the answer instead of as a step. */
export function drawnUnderTheAnswer(name: string): boolean {
  return toolEntry(name)?.hidden === true;
}

function finished(calls: readonly ToolCall[] | undefined, name: string): ToolCall[] {
  return (calls ?? []).filter((call) => call.name === name && call.status === "completed");
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
export type SetupKind = "agent" | "routine" | "connection";

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

const SETUP_KINDS: readonly string[] = ["agent", "routine", "connection"];

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

export function memoryChangesOf(calls: readonly ToolCall[] | undefined): MemoryChange[] {
  return (calls ?? []).flatMap((call) => {
    const forgot = call.name === "delete_memory";
    if (call.status !== "completed" || !(forgot || SAVES.has(call.name))) return [];
    const { name, description } = call.args;
    // The index the agent keeps for itself is not a note about anybody.
    if (name === "MEMORY.md") return [];
    const label = typeof description === "string" && description ? description : name;
    return typeof label === "string" && label ? [{ callId: call.id, forgot, label }] : [];
  });
}
