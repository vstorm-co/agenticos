import { describe, expect, it } from "vitest";

import { LAYOUTS, resolveAudience, SPAN_CLASS, visibleSections, type AudienceId } from "./layouts";
import { WIDGETS } from "./registry";
import { Perm, type Permission } from "@/types/permissions";

const AUDIENCES = Object.keys(LAYOUTS) as AudienceId[];

describe("resolveAudience", () => {
  it.each([
    ["owner", false, "steward"],
    ["admin", false, "steward"],
    ["builder", false, "builder"],
    ["operator", false, "operator"],
    ["member", false, "member"],
    ["viewer", false, "viewer"],
  ] as const)("role %s -> %s", (role, isAppAdmin, expected) => {
    expect(resolveAudience(role, isAppAdmin)).toBe(expected);
  });

  it("the app admin outranks whatever role they hold", () => {
    expect(resolveAudience("viewer", true)).toBe("app_admin");
    expect(resolveAudience("", true)).toBe("app_admin");
  });

  it("an unknown custom role lands on the member layout, not a wider one", () => {
    expect(resolveAudience("analyst", false)).toBe("member");
    expect(resolveAudience("", false)).toBe("member");
  });
});

describe("the layouts", () => {
  it("every entry names a widget the registry has, with a span the grid knows", () => {
    for (const audience of AUDIENCES) {
      for (const section of LAYOUTS[audience]) {
        for (const entry of section.entries) {
          expect(WIDGETS[entry.widget], `${audience}/${section.id}/${entry.widget}`).toBeTruthy();
          expect(SPAN_CLASS[entry.span], `${audience}/${section.id}/${entry.widget}`).toBeTruthy();
        }
      }
    }
  });

  it("the app admin's layout is the deployment strip over the steward's", () => {
    const [deployment, ...rest] = LAYOUTS.app_admin;

    expect(deployment?.id).toBe("deployment");
    expect(rest).toEqual(LAYOUTS.steward);
  });

  it("the viewer's my-agents carries its own title", () => {
    const entry = LAYOUTS.viewer[0]?.entries.find((candidate) => candidate.widget === "my-agents");

    expect(entry?.titleKey).toBe("widgets.my-agents.sharedTitle");
  });

  it("member and viewer pages are untitled - no section chrome for one section", () => {
    for (const audience of ["member", "viewer"] as const) {
      expect(LAYOUTS[audience]).toHaveLength(1);
      expect(LAYOUTS[audience][0]?.titleKey).toBeNull();
    }
  });

  it("offers the sandbox section only where a gate could pass it", () => {
    // The cards gate on `connections:view`, held by owner, admin, builder and
    // operator (`ROLE_PERMS`) - so all four carry the section and member and
    // viewer, who hold neither connections permission, do not. Listing it on a
    // layout whose gate can never pass would be an entry no caller can see.
    const carrying = AUDIENCES.filter((audience) =>
      LAYOUTS[audience].some((section) => section.id === "sandboxes"),
    );

    expect(carrying).toEqual(["app_admin", "steward", "operator", "builder"]);
  });
});

describe("visibleSections", () => {
  const holds =
    (...held: Permission[]) =>
    (permission: Permission) =>
      held.includes(permission);

  it("drops a section whose every widget is refused, heading included", () => {
    // A viewer holds agents:view and collections:view; the steward layout's
    // attention and people sections have nothing for them.
    const sections = visibleSections(
      "steward",
      holds(Perm.agentsView, Perm.collectionsView),
      false,
    );

    expect(sections.map((section) => section.id)).toEqual(["attention", "workspace"]);
    expect(sections[0]?.entries.map((entry) => entry.widget)).toEqual(["knowledge-freshness"]);
    expect(sections[1]?.entries.map((entry) => entry.widget)).toEqual(["my-agents"]);
  });

  it("a caller with nothing sees nothing - and no empty headings either", () => {
    expect(visibleSections("steward", () => false, false)).toEqual([]);
  });

  it("the app admin passes every gate on their own layout", () => {
    const sections = visibleSections("app_admin", () => true, true);
    const widgets = sections.flatMap((section) => section.entries.map((entry) => entry.widget));

    expect(sections.map((section) => section.id)[0]).toBe("deployment");
    expect(widgets).toContain("platform");
    expect(widgets).toContain("approvals");
  });

  it("an org admin never sees the deployment strip", () => {
    const sections = visibleSections("steward", () => true, false);

    expect(sections.map((section) => section.id)).not.toContain("deployment");
  });

  it("withholds the sandbox section, heading included, without connections:view", () => {
    // Not rendered and then 403'd: a caller who cannot ask a host what it runs
    // must not be told the section exists.
    const sections = visibleSections("steward", holds(Perm.runsView, Perm.membersManage), false);

    expect(sections.map((section) => section.id)).not.toContain("sandboxes");
  });

  it("gives an operator the sandbox section on the strength of connections:view", () => {
    const sections = visibleSections("operator", holds(Perm.connectionsView), false);

    expect(sections.map((section) => section.id)).toEqual(["sandboxes"]);
    expect(sections[0]?.entries.map((entry) => entry.widget)).toEqual([
      "sandbox-capacity",
      "sandbox-policy",
      "sandbox-sessions",
    ]);
  });

  it("does not offer the sandbox cards for connections:manage alone", () => {
    // The cards gate on the read, and the catalog implies neither permission
    // from the other - the same rule the backend keeps. A real manage-holding
    // role also holds the view; a caller with only manage is not one.
    const sections = visibleSections("builder", holds(Perm.connectionsManage), false);

    expect(sections.map((section) => section.id)).not.toContain("sandboxes");
  });
});
