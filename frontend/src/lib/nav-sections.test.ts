import { describe, expect, it } from "vitest";

import { NAV_GROUPS, navItemVisible, navSectionFor } from "./nav-sections";
import { ROUTES } from "./constants";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

describe("navSectionFor", () => {
  it("names the entry and its group's hue, and says when the path is the section's own page", () => {
    expect(navSectionFor("/agents")).toMatchObject({ domain: "build", isRoot: true });
    expect(navSectionFor("/agents")?.item.href).toBe("/agents");
    expect(navSectionFor("/rag")).toMatchObject({ domain: "knowledge", isRoot: true });
    expect(navSectionFor("/connectors")).toMatchObject({ domain: "workspace", isRoot: true });
    expect(navSectionFor("/dashboard")).toMatchObject({ domain: "use", isRoot: true });
    expect(navSectionFor("/agent-messages")).toMatchObject({ domain: "use", isRoot: true });
    expect(navSectionFor("/agent-messages")?.item.href).toBe("/agent-messages");
  });

  it("places a sub-page in its section without calling it the section's page", () => {
    expect(navSectionFor("/agents/abc")).toMatchObject({ domain: "build", isRoot: false });
    // The Advanced connections are sub-pages of Connectors, not entries of their own.
    expect(navSectionFor("/connectors/vault")).toMatchObject({
      domain: "workspace",
      isRoot: false,
    });
  });

  it("calls each tab of a tabbed section its page, and nothing deeper", () => {
    // The admin page is its tabs, each a path of its own; it lost its icon
    // because none of them was exactly `/admin`.
    expect(navSectionFor("/admin/users")).toMatchObject({ domain: "admin", isRoot: true });
    expect(navSectionFor("/en/admin/system")).toMatchObject({ isRoot: true });
    expect(navSectionFor("/admin/users/u-1")).toMatchObject({ isRoot: false });
  });

  it("strips a locale prefix before it decides", () => {
    expect(navSectionFor("/en/skills")).toMatchObject({ domain: "knowledge", isRoot: true });
  });

  it("answers null outside every section", () => {
    expect(navSectionFor("/settings/profile")).toBeNull();
  });
});

describe("the Connectors nav entry", () => {
  const connectors = () => {
    const group = NAV_GROUPS.find((g) => g.labelKey === "connections");
    return group?.items.find((item) => item.labelKey === "connectors");
  };
  const holding =
    (...granted: Permission[]) =>
    (permission: Permission) =>
      granted.includes(permission);

  it("is the one entry in the connections group, opening to any of its four areas", () => {
    const group = NAV_GROUPS.find((g) => g.labelKey === "connections");
    expect(group?.items).toEqual([
      expect.objectContaining({
        labelKey: "connectors",
        href: ROUTES.CONNECTORS,
        permissions: [Perm.agentsView, Perm.secretsView, Perm.connectionsView, Perm.networksView],
      }),
    ]);
  });

  it("shows to a role that can see only the vault", () => {
    expect(navItemVisible(connectors()!, holding(Perm.secretsView))).toBe(true);
  });

  it("shows to a role that can see only the connections", () => {
    expect(navItemVisible(connectors()!, holding(Perm.connectionsView))).toBe(true);
  });

  it("shows to a role that can see only agents", () => {
    expect(navItemVisible(connectors()!, holding(Perm.agentsView))).toBe(true);
  });

  it("shows to a role that can see only networks", () => {
    expect(navItemVisible(connectors()!, holding(Perm.networksView))).toBe(true);
  });

  it("stays hidden from a role with none of the three", () => {
    expect(navItemVisible(connectors()!, holding(Perm.workflowsView))).toBe(false);
  });
});

describe("role navigation preferences", () => {
  const item = (labelKey: string) =>
    NAV_GROUPS.flatMap((group) => group.items).find((entry) => entry.labelKey === labelKey)!;

  it("can hide both permission-gated and ungated entries without granting permissions", () => {
    expect(navItemVisible(item("agents"), () => true, ["agents"])).toBe(false);
    expect(navItemVisible(item("chat"), () => true, ["chat"])).toBe(false);
    expect(navItemVisible(item("agents"), () => false, [])).toBe(false);
    expect(navItemVisible(item("agents"), () => true, [])).toBe(true);
  });

  it("keeps recovery entries even if stale or invalid preferences name them", () => {
    for (const name of ["dashboard", "organizations", "adminOverview"]) {
      expect(navItemVisible(item(name), () => true, [name], false)).toBe(true);
    }
  });

  it("hides every configurable entry while permissions or policy are unknown", () => {
    for (const entry of NAV_GROUPS.flatMap((group) => group.items)) {
      const recovery = ["dashboard", "organizations", "adminOverview"].includes(entry.labelKey);
      expect(navItemVisible(entry, () => true, [], false)).toBe(recovery);
    }
  });
});
