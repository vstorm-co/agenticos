import { describe, expect, it } from "vitest";

import {
  AGENT_BUILDER,
  KB_DETAIL,
  ORG_MEMBERS,
  ORG_ROLES,
  pageHasSteps,
  pageKey,
  SETTINGS_DETAIL,
  stepsForPage,
  TOUR_STEPS,
  visibleTourSteps,
  WORKSPACE_DETAIL,
} from "./tour";
import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

// The curated launch pass a caller with no permissions sees: the interstitials
// and the ungated highlights, in order. Every stop gated on a view or edit
// permission drops out — including the whole builder walk, which is agents:view.
const UNGATED_LAUNCH = [
  "welcome",
  "dashboard-actions",
  "dashboard-filters",
  "chat-start",
  "chat-agent-picker",
  "finish",
];

// Every builder stop, in the order the "?" walks them. The launch pass takes a
// subset of these (instructions, tools, publish).
const BUILDER_STEPS = [
  "agent-instructions",
  "agent-model",
  "agent-toolbox",
  "agent-mcp",
  "agent-knowledge",
  "agent-skills",
  "agent-limits",
  "agent-availability",
  "agent-history",
  "agent-publish",
];

// Every collection-detail stop, in the order the "?" walks them. The launch
// pass takes one of these (kb-documents).
const KB_STEPS = ["kb-header", "kb-documents", "kb-ingestion", "kb-sync"];

// The organization detail walk: the members page (profile, then the list), then
// across into the roles matrix. None are inTour — orgs is a "?"-only section.
const ORG_STEPS = ["org-profile", "org-members", "org-roles"];

describe("pageKey", () => {
  it("collapses every concrete builder route onto the one builder identity", () => {
    expect(pageKey("/agents/abc-123")).toBe(AGENT_BUILDER);
    expect(pageKey("/agents/abc-123/anything")).toBe(AGENT_BUILDER);
  });

  it("collapses every concrete collection route onto the one KB identity", () => {
    expect(pageKey("/rag/abc-123")).toBe(KB_DETAIL);
    expect(pageKey("/rag/abc-123/anything")).toBe(KB_DETAIL);
  });

  it("splits the two organization detail routes onto their own identities", () => {
    expect(pageKey("/orgs/abc-123/members")).toBe(ORG_MEMBERS);
    expect(pageKey("/orgs/abc-123/roles")).toBe(ORG_ROLES);
  });

  it("collapses each settings tab and each workspace onto one identity", () => {
    expect(pageKey(ROUTES.SETTINGS_PROFILE)).toBe(SETTINGS_DETAIL);
    expect(pageKey(ROUTES.SETTINGS_SLASH_COMMANDS)).toBe(SETTINGS_DETAIL);
    expect(pageKey("/workspaces/abc-123")).toBe(WORKSPACE_DETAIL);
  });
});

describe("MCP catalog stops", () => {
  it("marks the catalog controls optional so an empty catalog drops them", () => {
    // filter, custom-add and connect render only inside the list — absent on an
    // empty catalog — so they must skip rather than strand the walk. The catalog
    // stop itself is not optional: its target moves onto the empty-state card.
    const byId = new Map(TOUR_STEPS.map((step) => [step.id, step]));
    expect(byId.get("mcp-filter")?.optional).toBe(true);
    expect(byId.get("mcp-add")?.optional).toBe(true);
    expect(byId.get("mcp-connect")?.optional).toBe(true);
    expect(byId.get("mcp-catalog")?.optional).toBeUndefined();
  });

  it("leaves the list routes and other pages as their own route", () => {
    expect(pageKey(ROUTES.AGENTS)).toBe(ROUTES.AGENTS);
    expect(pageKey(ROUTES.RAG)).toBe(ROUTES.RAG);
    expect(pageKey(ROUTES.ORGS)).toBe(ROUTES.ORGS);
    expect(pageKey(ROUTES.CHAT)).toBe(ROUTES.CHAT);
  });
});

describe("visibleTourSteps", () => {
  it("is the inTour steps, not every step, for a caller who can do everything", () => {
    const launch = visibleTourSteps(() => true);
    expect(launch).toEqual(TOUR_STEPS.filter((step) => step.inTour));
    // A strict subset — the "?"-only stops are left out of the walkthrough.
    expect(launch.length).toBeLessThan(TOUR_STEPS.length);
  });

  it("keeps only the ungated launch steps when the caller can do nothing", () => {
    expect(visibleTourSteps(() => false).map((step) => step.id)).toEqual(UNGATED_LAUNCH);
  });

  it("steps into the builder on the launch pass — one stop per tab", () => {
    const launch = visibleTourSteps(() => true).map((step) => step.id);
    // One per builder tab, so a first login gets a line on each section.
    for (const id of [
      "agent-instructions",
      "agent-toolbox",
      "agent-knowledge",
      "agent-skills",
      "agent-limits",
      "agent-availability",
      "agent-history",
      "agent-publish",
    ]) {
      expect(launch).toContain(id);
    }
    // …but not the sub-cards inside a tab — those are "?"-only.
    expect(launch).not.toContain("agent-model");
    expect(launch).not.toContain("agent-mcp");
  });

  it("gives a view-only member the builder and collection walks but not the publish stop", () => {
    // Instructions and the toolbox render for anyone who may view an agent, and
    // the collection's documents for anyone who may view a collection; Publish
    // is agents:publish, which a Viewer lacks, so that stop drops. The
    // edit-gated create buttons (agents-new, skills-new, …) drop too.
    const held = new Set<Permission>([Perm.agentsView, Perm.skillsView, Perm.collectionsView]);
    expect(visibleTourSteps((permission) => held.has(permission)).map((step) => step.id)).toEqual([
      "welcome",
      "dashboard-actions",
      "dashboard-filters",
      "chat-start",
      "chat-agent-picker",
      "agent-instructions",
      "agent-toolbox",
      "agent-knowledge",
      "agent-skills",
      "agent-limits",
      "agent-availability",
      "agent-history",
      "kb-documents",
      "mcp-catalog",
      "finish",
    ]);
  });

  it("includes a stop once the caller holds the permission its target needs", () => {
    const ids = visibleTourSteps((permission) => permission === Perm.agentsEdit).map(
      (step) => step.id,
    );
    expect(ids).toContain("agents-new");
  });

  it("never surfaces a '?'-only step in the walkthrough, whatever the caller holds", () => {
    expect(visibleTourSteps(() => true).map((step) => step.id)).not.toContain("chat-composer");
  });
});

describe("stepsForPage", () => {
  it("returns every highlight on a standalone page — launch and '?'-only — never an interstitial", () => {
    expect(stepsForPage(ROUTES.CHAT, () => true).map((step) => step.id)).toEqual([
      "chat-start",
      "chat-agent-picker",
      "chat-composer",
      "chat-model-picker",
    ]);
  });

  it("walks the list and then the whole builder when asked from the Agents list", () => {
    expect(stepsForPage(ROUTES.AGENTS, () => true).map((step) => step.id)).toEqual([
      "agents-new",
      "agents-filters",
      ...BUILDER_STEPS,
    ]);
  });

  it("walks only the builder when asked from a builder route — the reader is past the list", () => {
    expect(stepsForPage("/agents/some-id", () => true).map((step) => step.id)).toEqual(
      BUILDER_STEPS,
    );
  });

  it("gives Settings and a workspace their own '?' stop, from any of their routes", () => {
    // Settings collapses its four tabs onto one identity, so help opened on any of
    // them lands the same stop; a workspace detail has its own.
    expect(stepsForPage(ROUTES.SETTINGS_NOTIFICATIONS, () => true).map((s) => s.id)).toEqual([
      "settings-tabs",
    ]);
    expect(stepsForPage("/workspaces/some-id", () => true).map((s) => s.id)).toEqual([
      "workspaces-detail",
    ]);
  });

  it("is richer than the launch pass for the same section", () => {
    const onPage = stepsForPage(ROUTES.AGENTS, () => true);
    const inLaunch = visibleTourSteps(() => true).filter(
      (step) => step.page === ROUTES.AGENTS || step.page === AGENT_BUILDER,
    );
    expect(onPage.length).toBeGreaterThan(inLaunch.length);
  });

  it("is permission-filtered the same way the tour is", () => {
    // agents-new is edit-gated, agents-filters is not, and the builder walk is
    // agents:view — a caller who can do nothing still gets the one ungated stop.
    expect(stepsForPage(ROUTES.AGENTS, () => false).map((step) => step.id)).toEqual([
      "agents-filters",
    ]);
    expect(
      stepsForPage(ROUTES.AGENTS, (permission) => permission === Perm.agentsEdit).map(
        (step) => step.id,
      ),
    ).toEqual(["agents-new", "agents-filters"]);
  });

  it("hands the builder walk to anyone who may view an agent", () => {
    expect(
      stepsForPage("/agents/some-id", (permission) => permission === Perm.agentsView).map(
        (step) => step.id,
      ),
    ).toEqual(BUILDER_STEPS.filter((id) => id !== "agent-publish"));
  });

  it("walks the list and then the whole collection when asked from the Knowledge list", () => {
    expect(stepsForPage(ROUTES.RAG, () => true).map((step) => step.id)).toEqual([
      "knowledge-new",
      "knowledge-tabs",
      "knowledge-integrations",
      "knowledge-add-integration",
      ...KB_STEPS,
    ]);
  });

  it("walks the three activity tabs on the '?' pass, approvals first for a decider", () => {
    // The run drawer's stop rides along, and is `optional` because it only
    // mounts once a run is focused - the walk drops it rather than pinning a
    // caption to nothing when the drawer is closed.
    expect(stepsForPage(ROUTES.RUNS, () => true).map((step) => step.id)).toEqual([
      "activity-overview",
      "activity-approvals",
      "activity-runs",
      "activity-spend",
      "run-detail-input",
    ]);
  });

  it("drops the approvals tab for a caller who may see runs but not decide them", () => {
    const held = new Set<Permission>([Perm.runsView]);
    expect(
      stepsForPage(ROUTES.RUNS, (permission) => held.has(permission)).map((s) => s.id),
    ).toEqual(["activity-overview", "activity-runs", "activity-spend", "run-detail-input"]);
  });

  it("walks only the collection when asked from a collection route — past the list", () => {
    expect(stepsForPage("/rag/some-id", () => true).map((step) => step.id)).toEqual(KB_STEPS);
  });

  it("chains the two organization routes into one walk from the Workspaces list", () => {
    expect(stepsForPage(ROUTES.ORGS, () => true).map((step) => step.id)).toEqual([
      "orgs-new",
      ...ORG_STEPS,
    ]);
  });

  it("walks members then across into roles from a members route", () => {
    expect(stepsForPage("/orgs/some-id/members", () => true).map((step) => step.id)).toEqual(
      ORG_STEPS,
    );
  });

  it("walks only the roles matrix from a roles route — the last page of the flow", () => {
    expect(stepsForPage("/orgs/some-id/roles", () => true).map((step) => step.id)).toEqual([
      "org-roles",
    ]);
  });

  it("deepens the MCP page component by component", () => {
    expect(stepsForPage(ROUTES.MCP_SERVERS, () => true).map((step) => step.id)).toEqual([
      "mcp-catalog",
      "mcp-filter",
      "mcp-add",
      "mcp-connect",
    ]);
  });

  it("is empty for a page the tour does not cover", () => {
    expect(stepsForPage(ROUTES.PROFILE, () => true)).toEqual([]);
  });
});

describe("pageHasSteps", () => {
  // What the header "?" asks before rendering itself, and why it is separate from
  // `stepsForPage`: it answers without a permission set, so the button stays free
  // of the permission query in the twenty headers that render it.
  it("is false for the surfaces that render a header but are never walked", () => {
    // Both render `PageHeader`, and neither is in the registry.
    expect(pageHasSteps("/admin/users")).toBe(false);
    expect(pageHasSteps("/dev/components")).toBe(false);
  });

  it("is true for a covered page, including a detail route", () => {
    expect(pageHasSteps(ROUTES.AGENTS)).toBe(true);
    expect(pageHasSteps("/agents/some-id")).toBe(true);
    expect(pageHasSteps("/rag/some-id")).toBe(true);
  });

  it("ignores permissions, so a page whose stops are all gated still offers help", () => {
    // `/skills` carries an edit-gated stop and a view-gated one. A Viewer sees a
    // shorter walk, not no button — and a walk that a permission does empty is
    // closed by `useOnboardingTour`, not prejudged here.
    expect(pageHasSteps(ROUTES.SKILLS)).toBe(true);
  });
});

describe("the Routines page", () => {
  it("has stops, so its header renders a help button at all", () => {
    // A page absent from this registry renders no "?" - `pageHasSteps` - so the
    // feature ships invisible to everyone who learns the product through the
    // walkthrough. That is the silent failure, and this is the guard.
    expect(pageHasSteps(ROUTES.ROUTINES)).toBe(true);
  });

  it("gates the create stop on the run floor a trigger is made at", () => {
    // A Viewer with one explicit run grant may create a routine, and the page
    // hides the buttons on the same test - so an ungated step would wait four
    // seconds for a control a refusal never mounted.
    const refused = stepsForPage(ROUTES.ROUTINES, (perm) => perm !== "agents:run").map(
      (step) => step.id,
    );
    const allowed = stepsForPage(ROUTES.ROUTINES, () => true).map((step) => step.id);

    expect(refused).toEqual(["routines-list"]);
    expect(allowed).toEqual(["routines-list", "routines-create"]);
  });
});
