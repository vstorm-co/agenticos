import { describe, expect, it } from "vitest";

import { ROW_CLASS, SPAN_CLASS } from "./layouts";
import {
  accentDecoration,
  isAccentColour,
  isPresetAccent,
  normaliseAccent,
  WIDGET_IDS,
  WIDGETS,
  type WidgetId,
} from "./registry";
import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

const canOnly =
  (...held: Permission[]) =>
  (permission: Permission) =>
    held.includes(permission);

const NOBODY = () => false;

/** Which single permission opens each widget - the truth table of the page. */
const GATE_TABLE: Record<WidgetId, Permission | "app_admin"> = {
  summary: Perm.runsView,
  platform: "app_admin",
  health: "app_admin",
  "top-orgs": "app_admin",
  "platform-ratings": "app_admin",
  runs: Perm.runsView,
  outcomes: Perm.runsView,
  surfaces: Perm.runsView,
  agents: Perm.runsView,
  latency: Perm.runsView,
  "active-users": Perm.runsView,
  "top-people": Perm.runsView,
  spend: Perm.runsView,
  "model-mix": Perm.runsView,
  "version-compare": Perm.runsView,
  approvals: Perm.approvalsDecide,
  "recent-failures": Perm.runsView,
  "budget-headroom": Perm.runsView,
  "mcp-health": Perm.mcpManage,
  "knowledge-freshness": Perm.collectionsView,
  members: Perm.membersManage,
  "org-ratings": Perm.runsView,
  "my-agents": Perm.agentsView,
  conversations: Perm.agentsRun,
  "my-activity": Perm.agentsRun,
  "my-top-agents": Perm.agentsRun,
  "my-quality": Perm.agentsRun,
  "shared-with-you": Perm.agentsView,
  "sandbox-capacity": Perm.connectionsView,
  "sandbox-sessions": Perm.connectionsView,
  "sandbox-policy": Perm.connectionsView,
};

describe("the widget catalog", () => {
  it("holds all thirty-one widgets", () => {
    expect(WIDGET_IDS).toHaveLength(31);
  });

  it.each(WIDGET_IDS)("%s opens on exactly its own permission", (id) => {
    const expected = GATE_TABLE[id];
    const { gate } = WIDGETS[id];

    if (expected === "app_admin") {
      expect(gate(NOBODY, true)).toBe(true);
      expect(gate(() => true, false)).toBe(false);
    } else {
      expect(gate(canOnly(expected), false)).toBe(true);
      // Holding everything except the gate's permission is not enough.
      expect(
        gate((permission) => permission !== expected, false),
        `${id} must demand ${expected} and nothing else`,
      ).toBe(false);
    }
  });

  it("shows a caller with no permissions nothing at all", () => {
    const visible = WIDGET_IDS.filter((id) => WIDGETS[id].gate(NOBODY, false));

    expect(visible).toEqual([]);
  });

  it("every widget's default span is a class the grid knows", () => {
    for (const id of WIDGET_IDS) {
      expect(SPAN_CLASS[WIDGETS[id].defaultSpan], id).toBeTruthy();
    }
  });

  it("every widget's default height is a class the grid knows", () => {
    for (const id of WIDGET_IDS) {
      expect(ROW_CLASS[WIDGETS[id].defaultRows], id).toBeTruthy();
    }
  });

  it("every see-all destination is a route that exists", () => {
    const known = new Set<string>(
      Object.values<unknown>(ROUTES).filter((value) => typeof value === "string") as string[],
    );
    for (const id of WIDGET_IDS) {
      const destination = WIDGETS[id].seeAll;
      if (destination !== undefined) {
        expect(known.has(destination), `${id} points at ${destination}`).toBe(true);
      }
    }
  });
});

describe("section accents", () => {
  it("recognises a named preset and nothing else as a preset", () => {
    expect(isPresetAccent("violet")).toBe(true);
    expect(isPresetAccent("#ff0000")).toBe(false);
    expect(isPresetAccent("neutral")).toBe(false);
  });

  it("treats only a preset or a valid hex as a colour that paints", () => {
    expect(isAccentColour("blue")).toBe(true);
    expect(isAccentColour("#A1B2C3")).toBe(true);
    expect(isAccentColour("neutral")).toBe(false);
    expect(isAccentColour(null)).toBe(false);
    expect(isAccentColour("not-a-colour")).toBe(false);
  });

  it("canonicalises a stored accent, lower-casing a hex and dropping the unknown", () => {
    expect(normaliseAccent(null)).toBe("neutral");
    expect(normaliseAccent("neutral")).toBe("neutral");
    expect(normaliseAccent("green")).toBe("green");
    expect(normaliseAccent("#AABBCC")).toBe("#aabbcc");
    expect(normaliseAccent("chartreuse")).toBe("neutral");
  });

  it("decorates a preset with its class, a hex inline, and neutral with nothing", () => {
    expect(accentDecoration("amber")).toEqual({ className: "dash-accent-amber" });
    expect(accentDecoration("#AABBCC")).toEqual({
      className: "",
      style: { "--dash-solid": "#aabbcc" },
    });
    expect(accentDecoration("neutral")).toEqual({ className: "" });
  });
});
