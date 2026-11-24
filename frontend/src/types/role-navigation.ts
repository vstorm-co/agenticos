import type { OrgRole } from "./organization";

export interface RoleNavigationPolicy {
  hidden_items: Record<OrgRole, string[]>;
  configurable_items: string[];
  editable_roles: OrgRole[];
}

export interface UpdateRoleNavigation {
  organizationId: string;
  role: OrgRole;
  hiddenItems: string[];
}
