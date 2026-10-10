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
}

/** A partial change. `description: null` clears it; an absent key leaves it. */
export interface GroupUpdate {
  name?: string;
  description?: string | null;
  icon?: GroupIcon | null;
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

/** One thing shared with a group, at the level it was shared at (#2072). */
export interface GroupResource {
  kind: "agent" | "collection" | "skill" | "context" | "artifact";
  id: string;
  name: string;
  level: GrantLevel;
}

export interface GroupResourceList {
  items: GroupResource[];
  total: number;
}
