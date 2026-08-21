import type { MyPermissions, RoleCatalog } from "@/types/permissions";

/**
 * A role catalog with real permission sets, for anything that renders a role
 * picker.
 *
 * The picker is derived from these sets - which roles a caller may hand out is
 * arithmetic over them, not a list - so a fixture of empty ones answers nothing:
 * every role reaches every other, so none strictly outranks any, and the picker
 * offers nothing at all. Both invite dialogs had exactly that fixture, from when
 * the picker was "the catalog, minus owner" and the permissions were decoration
 * (#1028).
 *
 * This mirrors the shape of the built-ins rather than their contents: each role
 * holds everything the one below it does, plus something of its own, which is
 * what makes `assignableRoles` answer the same sets it answers in the product -
 * an Owner offering five roles, an Admin offering four and not its own.
 *
 * Deliberately in `test-utils`, outside the coverage `include` list, so a helper
 * does not drag the 100% gate along.
 */
export const ROLE_CATALOG: RoleCatalog = {
  all_permissions: [],
  resource_permissions: [],
  roles: [
    {
      name: "owner",
      permissions: [
        { permission: "roles:manage", scope: "all" },
        { permission: "members:manage", scope: "all" },
        { permission: "agents:edit", scope: "all" },
        { permission: "agents:run", scope: "all" },
        { permission: "agents:view", scope: "all" },
      ],
    },
    {
      name: "admin",
      permissions: [
        { permission: "members:manage", scope: "all" },
        { permission: "agents:edit", scope: "all" },
        { permission: "agents:run", scope: "all" },
        { permission: "agents:view", scope: "all" },
      ],
    },
    {
      name: "builder",
      permissions: [
        { permission: "agents:edit", scope: "all" },
        { permission: "agents:run", scope: "all" },
        { permission: "agents:view", scope: "all" },
      ],
    },
    {
      name: "operator",
      permissions: [
        { permission: "agents:run", scope: "all" },
        { permission: "agents:view", scope: "all" },
      ],
    },
    { name: "member", permissions: [{ permission: "agents:view", scope: "all" }] },
    { name: "viewer", permissions: [{ permission: "agents:view", scope: "own" }] },
  ],
};

/** What `/me/permissions` answers for a caller holding `role` in {@link ROLE_CATALOG}. */
export function permissionsOf(role: string): MyPermissions {
  return {
    organization_id: "org-1",
    role: role as MyPermissions["role"],
    is_app_admin: false,
    permissions: ROLE_CATALOG.roles.find((entry) => entry.name === role)?.permissions ?? [],
  };
}
