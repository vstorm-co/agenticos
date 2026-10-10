/**
 * Types for an organization's groups, mirroring the backend's `group` schemas.
 *
 * A group is a named set of the organization's members. It carries no
 * permissions of its own: what it is for is being shared with, so one grant
 * reaches everybody in it.
 */

import type { MembershipSource } from "./organization";
import type { GrantLevel } from "./sharing";

/** The marks a group may carry - lucide names, mirroring `GroupIcon` in `schemas/group.py`. */
export const GROUP_ICONS = [
  "users",
  "briefcase",
  "banknote",
  "megaphone",
  "headphones",
  "code",
  "scale",
  "heart-handshake",
  "truck",
  "flask-conical",
  "graduation-cap",
  "building",
] as const;

export type GroupIcon = (typeof GROUP_ICONS)[number];

export interface Group {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  icon: GroupIcon | null;
  /** The department's monthly cap, as the decimal string the API sends; null is none. */
  monthly_budget_usd: string | null;
  member_count: number;
  created_at: string;
}

export interface GroupList {
  items: Group[];
  total: number;
}

/** What creating a group sends. */
export interface GroupCreate {
  name: string;
  description: string | null;
  icon?: GroupIcon | null;
  monthly_budget_usd?: number | null;
}

/** A partial change. `description: null` clears it; an absent key leaves it. */
export interface GroupUpdate {
  name?: string;
  description?: string | null;
  icon?: GroupIcon | null;
  /** `null` removes the cap; an absent key keeps it. */
  monthly_budget_usd?: number | null;
}

export interface GroupMember {
  user_id: string;
  email: string;
  full_name: string | null;
  source: MembershipSource;
  /** Leads the group: adds and removes its members without administering the org. */
  is_lead: boolean;
  created_at: string;
}

export interface GroupMemberList {
  items: GroupMember[];
  total: number;
}

/** One thing shared with a group, at the level it was shared at (#2072). */
export interface GroupResource {
  kind: "agent" | "collection" | "skill" | "context" | "artifact" | "mcp_connection";
  id: string;
  name: string;
  level: GrantLevel;
}

/** Share several resources with a group from its page (#2072). */
export interface GroupShareRequest {
  items: { kind: GroupResource["kind"]; id: string }[];
  level: GrantLevel;
}

/** One department's month to date against its cap (#2072). Money arrives as decimal strings. */
export interface GroupSpend {
  group_id: string;
  name: string;
  icon: GroupIcon | null;
  member_count: number;
  monthly_budget_usd: string | null;
  spent_usd: string;
  run_count: number;
}

/** Every department's month, costliest first. A person in two counts in both. */
export interface GroupSpendList {
  since: string;
  items: GroupSpend[];
}

export interface GroupResourceList {
  items: GroupResource[];
  total: number;
}
