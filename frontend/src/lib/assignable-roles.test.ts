import { describe, expect, it } from "vitest";

import { assignableRoles, defaultAssignable } from "./assignable-roles";
import { ROLE_CATALOG } from "@/test-utils/role-catalog";
import type { RoleCatalog, RoleDefinition } from "@/types/permissions";

/**
 * The client's copy of `app.core.permissions.assignable_roles`, and the reason it
 * is a copy rather than a list: what a picker offers has to be the relation the
 * server enforces, or the control offers what the write refuses (#1028).
 *
 * The pairs asserted here are the ones the backend's own tests assert, so the two
 * can be read against each other.
 */
describe("assignableRoles", () => {
  it("offers an Owner every role but their own", () => {
    expect(assignableRoles(ROLE_CATALOG, "owner")).toEqual([
      "admin",
      "builder",
      "operator",
      "member",
      "viewer",
    ]);
  });

  it("offers an Admin no Admin, because nobody assigns their own level", () => {
    // Promoting a peer to your own level is an ownership decision, not a
    // management one - which is what "strictly outranks" buys.
    expect(assignableRoles(ROLE_CATALOG, "admin")).toEqual([
      "builder",
      "operator",
      "member",
      "viewer",
    ]);
  });

  it("offers nobody Owner, because no role outranks it", () => {
    for (const role of ROLE_CATALOG.roles) {
      expect(assignableRoles(ROLE_CATALOG, role.name)).not.toContain("owner");
    }
  });

  it("offers a Viewer nothing", () => {
    expect(assignableRoles(ROLE_CATALOG, "viewer")).toEqual([]);
  });

  it("measures a scope rather than comparing it as a string", () => {
    // A Member holds `agents:view` at `all` and a Viewer at `own`, so the Member
    // outranks the Viewer. Compared as strings, `all < own` alphabetically and
    // the answer inverts - which is the mistake `Scope` refuses to make on the
    // server and this refuses here.
    expect(assignableRoles(ROLE_CATALOG, "member")).toEqual(["viewer"]);
  });

  it("offers an unknown role nothing", () => {
    // The server's answer for one too: a role that holds nothing assigns
    // nothing, which is the safe direction for a picker to be wrong in.
    expect(assignableRoles(ROLE_CATALOG, "not-a-role")).toEqual([]);
    expect(assignableRoles(ROLE_CATALOG, "")).toEqual([]);
  });

  it("offers nothing before the catalog has answered", () => {
    expect(assignableRoles(undefined, "owner")).toEqual([]);
  });

  it("offers a custom role only what it outranks, not what its name suggests", () => {
    // The reason this is arithmetic and not a list. A Phase 2 role composed with
    // `members:manage` may invite - and used to be offered Admin, because the
    // ceiling this replaced compared against the literal role name (#696).
    const catalog: RoleCatalog = {
      ...ROLE_CATALOG,
      roles: [
        ...ROLE_CATALOG.roles,
        {
          // `OrgRole` is the six built-ins, so a Phase 2 name needs the cast -
          // the relation itself takes any role the catalog names.
          name: "inviter" as RoleDefinition["name"],
          permissions: [{ permission: "members:manage", scope: "all" }],
        },
      ],
    };

    const offered = assignableRoles(catalog, "inviter");

    expect(offered).not.toContain("admin");
    expect(offered).not.toContain("owner");
    // And nothing else either: it holds no `agents:*`, so it outranks none of
    // the roles that do.
    expect(offered).toEqual([]);
  });
});

describe("defaultAssignable", () => {
  it("starts on the preferred role where it is offered", () => {
    expect(defaultAssignable(["builder", "operator", "member", "viewer"], "member")).toBe("member");
  });

  it("falls to the least privileged on offer when the preferred one is not", () => {
    // Catalog order runs from most to least privileged, so the last is the
    // safest thing to seed a picker with.
    expect(defaultAssignable(["builder", "operator"], "member")).toBe("operator");
  });

  it("answers nothing when nothing is on offer", () => {
    expect(defaultAssignable([], "member")).toBe("");
  });
});
