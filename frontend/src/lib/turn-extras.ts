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
