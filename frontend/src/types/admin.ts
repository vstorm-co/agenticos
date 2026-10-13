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
  /**
   * Its earliest owner - who to ask about this tenant. Every field is null
   * together, for an organization whose last owner left, which is a state only
   * the deployment admin can fix and therefore one they have to be shown.
   */
  owner_user_id: string | null;
  owner_email: string | null;
  owner_name: string | null;
  created_at: string;
}

/** One member of a tenant, as the deployment admin inspecting it sees them. */
export interface AdminOrganizationMember {
  user_id: string;
  email: string;
  name: string | null;
  role: string;
}

/**
 * One organization in full for the admin's per-tenant page (#1245): its members
 * and roles, size, owner and budget - never the tenant's agents, conversations
 * or secrets, which the tenant boundary keeps to the tenant.
 */
export interface AdminOrganizationDetail extends AdminOrganization {
  members: AdminOrganizationMember[];
  /**
   * The serialized `Decimal` budget, which reaches the wire as a string that
   * keeps the column's precision - `"50.000000"`. Formatted with `Number(...)`
   * at the point of use, as the other budget surfaces do.
   */
  monthly_budget_usd: string | null;
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
