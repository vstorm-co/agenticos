/**
 * Types for directory group mappings, mirroring the backend's `directory` schemas.
 *
 * A mapping names a group as the directory knows it - an LDAP group DN, or a
 * value of an OIDC provider's groups claim - and says what signing in as one of
 * its members makes somebody here: a role in the organization and, optionally,
 * a place in one of its groups.
 */

import type { OrgRole } from "./organization";

export interface DirectoryMapping {
  id: string;
  organization_id: string;
  /** Stored case-folded, which is how the sync compares it. */
  external_group: string;
  role: OrgRole;
  group_id: string | null;
  /** Resolved for display; null when the mapping names no group. */
  group_name: string | null;
  created_at: string;
}

export interface DirectoryMappingList {
  items: DirectoryMapping[];
  total: number;
}

export interface DirectoryMappingCreate {
  external_group: string;
  role: OrgRole;
  group_id: string | null;
}
