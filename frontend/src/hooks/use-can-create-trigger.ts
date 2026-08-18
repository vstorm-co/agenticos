"use client";

import { useAgents } from "@/hooks/use-agents";

/**
 * Whether the caller may create a trigger on *any* agent - the floor for the
 * org-wide create controls that are not tied to one agent, the chat sidebar's
 * "New" menu and the Routines page's "New schedule".
 *
 * The floor is a per-agent signal, not the role-level `agents:run`: a Viewer
 * granted run on a single agent may create a trigger there, so the control has
 * to show for them even though their role reaches no agent. Reusing `useAgents`
 * keeps this off its own query key and lets the same list answer the agent
 * picker beside it.
 *
 * While the list is loading `agents` is empty and this returns false - the same
 * conservatism `usePermissions` applies, so a control is revealed once the data
 * says it may be rather than flashed and withdrawn.
 */
export function useCanCreateTrigger(): boolean {
  const { agents } = useAgents();
  return agents.some((agent) => agent.can_run);
}
