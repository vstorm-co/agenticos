/**
 * Types for the app-admin endpoints (/admin/stats, /admin/system,
 * /admin/organizations). One definition, shared by the admin pages and the
 * dashboard's deployment widgets - two copies would be two contracts.
 */

export interface AdminStats {
  total_users?: number;
  active_users_24h?: number;
  total_organizations?: number;
  total_agents?: number;
  total_conversations?: number;
  total_messages?: number;
}

export interface AdminOrganization {
  id: string;
  name: string;
  slug: string;
  is_personal: boolean;
  member_count: number;
  agent_count: number;
  created_at: string;
}

/**
 * Every status comes from a probe that ran - including `not_checked`, which is
 * a probe that was skipped and says why. There is no invented "unknown".
 */
export type CheckStatus = "healthy" | "unhealthy" | "unconfigured" | "not_checked";

export interface SystemCheck {
  key: string;
  status: CheckStatus;
  detail: string;
  latency_ms: number | null;
}

export interface SystemHealth {
  checked_at: string;
  checks: SystemCheck[];
}
