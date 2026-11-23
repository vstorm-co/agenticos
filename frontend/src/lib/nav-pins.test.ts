import { describe, expect, it } from "vitest";

import { buildNavLayout, isPinnable, navItemId, toggledPins } from "./nav-pins";
import { NAV_GROUPS, type NavItem } from "./nav-sections";

const allVisible = () => true;
const ids = (items: NavItem[]) => items.map(navItemId);

function layout(overrides: Partial<Parameters<typeof buildNavLayout>[0]> = {}) {
  return buildNavLayout({
    pinnedIds: [],
    pathname: "/dashboard",
    isVisible: allVisible,
    isAdmin: false,
    ...overrides,
  });
}

describe("buildNavLayout", () => {
  it("fixes Home, Chat, Inbox and Agent messages, with nothing pinned", () => {
    const result = layout();
    expect(ids(result.fixed)).toEqual(["dashboard", "chat", "inbox", "agentMessages"]);
    expect(result.pinned).toEqual([]);
    expect(result.current).toBeNull();
  });

  it("keeps pins in the order they were saved and drops repeats", () => {
    expect(ids(layout({ pinnedIds: ["skills", "agents", "skills"] }).pinned)).toEqual([
      "skills",
      "agents",
    ]);
  });

  it("ignores unknown ids, fixed ids and entries the caller may not see", () => {
    const result = layout({
      pinnedIds: ["retired", "chat", "agents", "skills"],
      isVisible: (item) => item.labelKey !== "skills",
    });
    expect(ids(result.pinned)).toEqual(["agents"]);
  });

  it("hides the admin entry from anyone who is not an admin, and never pins it for them", () => {
    const member = layout({ pinnedIds: ["adminOverview"] });
    expect(member.pinned).toEqual([]);
    expect(member.more.flatMap((section) => ids(section.items))).not.toContain("adminOverview");

    const admin = layout({ isAdmin: true, pinnedIds: ["adminOverview"] });
    expect(ids(admin.pinned)).toEqual(["adminOverview"]);
    expect(admin.more.at(-1)).toMatchObject({ labelKey: null });
  });

  it("groups More as the navigation table does, with no Monitoring group", () => {
    const labels = layout({ isAdmin: true }).more.map((section) => section.labelKey);
    expect(labels).toEqual([
      "apps",
      "build",
      "projects",
      "knowledge",
      "connections",
      "organization",
      null,
    ]);
  });

  it("leaves out a group with nothing visible", () => {
    const result = layout({ isVisible: (item) => item.labelKey === "agents" });
    expect(result.more.map((section) => section.labelKey)).toEqual(["build"]);
  });

  it("shows the current page when it is neither fixed nor pinned", () => {
    expect(layout({ pathname: "/en/skills/abc" }).current?.labelKey).toBe("skills");
  });

  it.each([
    ["fixed", "/chat", []],
    ["pinned", "/skills", ["skills"]],
    ["owned by no entry", "/settings/profile", []],
  ])("shows no current page when it is %s", (_name, pathname, pinnedIds) => {
    expect(layout({ pathname, pinnedIds }).current).toBeNull();
  });

  it("shows no current page the caller may not see", () => {
    expect(layout({ pathname: "/skills", isVisible: () => false }).current).toBeNull();
  });
});

describe("toggledPins", () => {
  it("appends an unpinned entry, so pins keep the order they were made in", () => {
    expect(toggledPins(["agents"], "skills")).toEqual(["agents", "skills"]);
  });

  it("removes a pinned entry", () => {
    expect(toggledPins(["agents", "skills"], "agents")).toEqual(["skills"]);
  });

  it("drops saved ids this build no longer knows", () => {
    expect(toggledPins(["retired", "agents"], "skills")).toEqual(["agents", "skills"]);
  });
});

describe("isPinnable", () => {
  it("accepts every listed entry and none of the fixed four", () => {
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        expect(isPinnable(item.labelKey), item.labelKey).toBe(group.labelKey !== null);
      }
    }
  });
});
