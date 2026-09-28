/**
 * Types for an organization's groups, mirroring the backend's `group` schemas.
 *
 * A group is a named set of the organization's members. It carries no
 * permissions of its own: what it is for is being shared with, so one grant
 * reaches everybody in it.
 */

import type { MembershipSource } from "./organization";

export interface Group {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
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
}

/** A partial change. `description: null` clears it; an absent key leaves it. */
export interface GroupUpdate {
  name?: string;
  description?: string | null;
}

export interface GroupMember {
  user_id: string;
  email: string;
  full_name: string | null;
  source: MembershipSource;
  created_at: string;
}

export interface GroupMemberList {
  items: GroupMember[];
  total: number;
}
