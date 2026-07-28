import type { OrgRole } from "./organization";

/**
 * A permission string as defined by the backend catalog (`app.core.permissions.Perm`).
 *
 * Typed as a template literal rather than a closed union on purpose: the server
 * owns the catalog, and a UI that hardcodes the list goes stale the moment a
 * permission is added. Call sites still get autocomplete-friendly narrowing via
 * the `Perm` constants below.
 */
export type Permission = `${string}:${string}`;

/** How much of a resource type a permission reaches. */
export type PermissionScope = "none" | "own" | "shared" | "team" | "all";

export interface PermissionEntry {
  permission: Permission;
  scope: PermissionScope;
}

export interface MyPermissions {
  organization_id: string;
  role: OrgRole | "";
  is_app_admin: boolean;
  permissions: PermissionEntry[];
}

export interface RoleDefinition {
  name: OrgRole;
  permissions: PermissionEntry[];
}

export interface RoleCatalog {
  all_permissions: Permission[];
  resource_permissions: Permission[];
  roles: RoleDefinition[];
}

/** The permissions the UI actually branches on, named so typos fail at build time. */
export const Perm = {
  agentsView: "agents:view",
  agentsEdit: "agents:edit",
  agentsPublish: "agents:publish",
  agentsRun: "agents:run",
  collectionsView: "collections:view",
  collectionsEdit: "collections:edit",
  skillsView: "skills:view",
  skillsEdit: "skills:edit",
  approvalsDecide: "approvals:decide",
  connectionsManage: "connections:manage",
  mcpManage: "mcp:manage",
  channelsManage: "channels:manage",
  membersManage: "members:manage",
  rolesManage: "roles:manage",
  orgSettings: "org:settings",
  orgDelete: "org:delete",
  budgetsManage: "budgets:manage",
  runsView: "runs:view",
  auditRead: "audit:read",
} as const satisfies Record<string, Permission>;
