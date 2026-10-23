import { describe, expect, it } from "vitest";

import {
  isDivider,
  isWidget,
  LAYOUTS,
  nearestRows,
  nearestSpan,
  resolveAudience,
  ROW_CLASS,
  rowCount,
  spanCols,
  SPAN_CLASS,
  stepRows,
  stepSpan,
  viewLayout,
  visibleSections,
  type AudienceId,
} from "./layouts";
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

  it("gives every audience the same arrangement, because the gate is what differs", () => {
    // Six hand-written variants said what a permission already says, and drifted
    // from each other every time a widget was added to one of them. The page a
    // member lands on is this list with everything they may not see removed.
    for (const audience of AUDIENCES) {
      expect(LAYOUTS[audience].map((section) => section.id)).toEqual(
        LAYOUTS.app_admin.map((section) => section.id),
      );
    }
  });

  it("carries a height on every card, not only a width", () => {
    // The default is a page somebody arranged on a real screen, and it renders
    // in the same fixed-row grid an arranged layout does - a height nobody can
    // see is not a default anybody chose.
    for (const section of LAYOUTS.app_admin) {
      for (const entry of section.entries) {
        expect(entry.rows, `${section.id}/${entry.widget}`).toBeTruthy();
      }
    }
  });

  it("renames the agents card for a viewer, the one thing a shared list must not claim", () => {
    // A viewer's `my-agents` lists what was shared with them, so "your agents"
    // is the single place the shared list would say something untrue.
    const viewerEntry = viewLayout("me", "viewer")
      .flatMap((section) => section.entries)
      .find((entry) => entry.widget === "my-agents");
    const stewardEntry = viewLayout("me", "steward")
      .flatMap((section) => section.entries)
      .find((entry) => entry.widget === "my-agents");

    expect(viewerEntry?.titleKey).toBe("widgets.my-agents.sharedTitle");
    expect(stewardEntry?.titleKey).toBeUndefined();
  });

  it("places no card twice", () => {
    // The arrangement this was taken from held `my-agents` twice, by accident.
    // A default that ships a duplicate is one every new person inherits.
    for (const audience of AUDIENCES) {
      const placed = LAYOUTS[audience].flatMap((section) =>
        section.entries.map((entry) => entry.widget),
      );
      expect(new Set(placed).size, audience).toBe(placed.length);
    }
  });
});

describe("visibleSections", () => {
  const holds =
    (...held: Permission[]) =>
    (permission: Permission) =>
      held.includes(permission);

  it("drops a section whose every widget is refused, heading included", () => {
    // A viewer holds agents:view and collections:view; their own view keeps the
    // cards those allow and the one card gated on being signed in.
    const sections = visibleSections(
      viewLayout("me", "viewer"),
      holds(Perm.agentsView, Perm.collectionsView),
      false,
    );

    expect(sections.map((section) => section.id)).toEqual(["workspace", "attention"]);
    expect(sections[0]?.entries.map((entry) => entry.widget)).toEqual([
      "my-agents",
      "shared-with-you",
    ]);
    expect(sections[1]?.entries.map((entry) => entry.widget)).toEqual(["notifications"]);
  });

  it("a caller with nothing still sees their own notifications, and nothing else", () => {
    expect(visibleSections(LAYOUTS.steward, () => false, false)).toEqual([
      {
        id: "attention",
        titleKey: "attention",
        entries: [{ widget: "notifications", span: "s6", rows: "r3" }],
      },
    ]);
  });

  it("opens the organization's view on its figures, and keeps the person's and the host's apart", () => {
    const sections = visibleSections(LAYOUTS.app_admin, () => true, true);
    const widgets = sections.flatMap((section) => section.entries.map((entry) => entry.widget));

    expect(sections[0]?.entries.map((entry) => entry.widget)).toEqual([
      "summary",
      "runs",
      "outcomes",
    ]);
    expect(widgets).not.toContain("my-agents");
    expect(widgets).not.toContain("platform");
  });

  it("gives the group and deployment views only cards that answer their question", () => {
    const usageCards = new Set([
      "summary",
      "runs",
      "outcomes",
      "agents",
      "spend",
      "activity-rhythm",
      "surfaces",
      "model-mix",
      "latency",
      "top-people",
    ]);
    const group = viewLayout("group", "steward").flatMap((section) => section.entries);
    const deployment = viewLayout("deployment", "app_admin").flatMap((section) => section.entries);

    // Every group card reads /stats/usage, the one endpoint that takes a group.
    expect(group.every((entry) => usageCards.has(entry.widget))).toBe(true);
    expect(deployment.map((entry) => entry.widget)).toEqual([
      "platform",
      "health",
      "background-jobs",
      "top-orgs",
      "platform-ratings",
    ]);
    // And an organization admin is refused all of the deployment's cards.
    expect(visibleSections(viewLayout("deployment", "steward"), () => true, false)).toEqual([]);
  });

  it("an org admin never sees the deployment strip", () => {
    // Everybody is offered the same arrangement, so what withholds the band is
    // the gate on its four cards - all four are app-admin-only, so the heading
    // goes with them.
    const sections = visibleSections(LAYOUTS.steward, () => true, false);

    expect(sections.map((section) => section.id)).not.toContain("deployment");
  });

  it("leaves the cards that are usually empty to the catalog", () => {
    // A default that leads with "nothing connected yet" in six places is the
    // page this arrangement replaced; those cards are one click away in
    // Customize, and every one of them is still in the registry.
    const placed = new Set(
      LAYOUTS.app_admin.flatMap((section) => section.entries.map((entry) => entry.widget)),
    );
    for (const widget of [
      "mcp-health",
      "channels",
      "routines",
      "knowledge-freshness",
      "sandbox-sessions",
    ] as const) {
      expect(placed.has(widget), widget).toBe(false);
      expect(WIDGETS[widget]).toBeTruthy();
    }
  });
});

describe("the grid vocabulary", () => {
  it("reads a span and a height as their counts", () => {
    expect(spanCols("s8")).toBe(8);
    expect(spanCols("s12")).toBe(12);
    expect(rowCount("r3")).toBe(3);
  });

  it("steps a width within the closed set and clamps at both ends", () => {
    expect(stepSpan("s6", 1)).toBe("s7");
    expect(stepSpan("s8", 1)).toBe("s12");
    expect(stepSpan("s3", -1)).toBe("s3");
    expect(stepSpan("s12", 1)).toBe("s12");
  });

  it("steps a height within the closed set and clamps at both ends", () => {
    expect(stepRows("r3", 1)).toBe("r4");
    expect(stepRows("r2", -1)).toBe("r2");
    expect(stepRows("r6", 1)).toBe("r6");
  });

  it("snaps a column count to the nearest allowed width, jumping the s8→s12 gap", () => {
    expect(nearestSpan(6)).toBe("s6");
    // Below the floor and above the ceiling clamp to the ends.
    expect(nearestSpan(1)).toBe("s3");
    expect(nearestSpan(99)).toBe("s12");
    // The gap: 9 and 10 are closer to s8, 11 and 12 to s12.
    expect(nearestSpan(9)).toBe("s8");
    expect(nearestSpan(11)).toBe("s12");
  });

  it("snaps a row count to the nearest allowed height", () => {
    expect(nearestRows(4)).toBe("r4");
    expect(nearestRows(0)).toBe("r2");
    expect(nearestRows(99)).toBe("r6");
  });

  it("every allowed height has a grid class", () => {
    for (const rows of ["r2", "r3", "r4", "r5", "r6"] as const) {
      expect(ROW_CLASS[rows]).toBeTruthy();
    }
  });
});

describe("isWidget / isDivider", () => {
  it("splits a widget placement from a section divider", () => {
    const widget = { widget: "runs", span: "s8" } as const;
    const legacy = { kind: "widget", widget: "spend", span: "s6" } as const;
    const divider = { kind: "section", label: "Usage", accent: "neutral" } as const;

    expect(isWidget(widget)).toBe(true);
    expect(isWidget(legacy)).toBe(true);
    expect(isWidget(divider)).toBe(false);
    expect(isDivider(divider)).toBe(true);
    expect(isDivider(widget)).toBe(false);
  });
});
