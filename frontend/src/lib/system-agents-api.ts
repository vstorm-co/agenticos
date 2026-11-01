/**
 * API client for the platform's own background roles (#2575).
 *
 * A role is work the platform does that needs a model - consolidating what people
 * told their agents, composing a briefing. Memory maintenance has a profile of its
 * own; the daily briefing is the organization's proactivity setting, listed here
 * with its history and edited where it lives.
 */

import { apiClient } from "./api-client";

export type SystemRole = "daily_briefing" | "memory_maintenance";

export interface SystemAgentRun {
  id: string;
  started_at: string;
  status: string;
  model_label: string | null;
  cost_usd: string;
  error: string | null;
}

export interface SystemAgent {
  role: SystemRole;
  enabled: boolean;
  model_profile_id: string | null;
  model_label: string | null;
  monthly_budget_usd: string | null;
  spent_this_month: string;
  /** Why a role that is on would do nothing: the starter agent it is recorded under is gone. */
  unavailable: "starter_agent" | null;
  /** Set where the role's model and limit live in another setting. */
  managed_in: "proactivity" | null;
  runs: SystemAgentRun[];
}

export interface SystemAgentUpdate {
  enabled: boolean;
  model_profile_id: string | null;
  monthly_budget_usd: string | null;
}

export async function listSystemAgents(): Promise<SystemAgent[]> {
  const page = await apiClient.get<{ items: SystemAgent[] }>("/system-agents");
  return page.items;
}

export async function updateSystemAgent(
  role: SystemRole,
  update: SystemAgentUpdate,
): Promise<SystemAgent> {
  return apiClient.put<SystemAgent>(`/system-agents/${role}`, update);
}
