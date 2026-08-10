import { describe, expect, it } from "vitest";

import { AGENT_BUILDER, pageKey, stepsForPage, TOUR_STEPS, visibleTourSteps } from "./tour";
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

describe("pageKey", () => {
  it("collapses every concrete builder route onto the one builder identity", () => {
    expect(pageKey("/agents/abc-123")).toBe(AGENT_BUILDER);
    expect(pageKey("/agents/abc-123/anything")).toBe(AGENT_BUILDER);
  });

  it("leaves the agents list and other pages as their own route", () => {
    expect(pageKey(ROUTES.AGENTS)).toBe(ROUTES.AGENTS);
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

  it("steps into the builder on the launch pass — instructions, tools, then publish", () => {
    const launch = visibleTourSteps(() => true).map((step) => step.id);
    expect(launch).toContain("agent-instructions");
    expect(launch).toContain("agent-toolbox");
    expect(launch).toContain("agent-publish");
    // …but not the "?"-only builder stops.
    expect(launch).not.toContain("agent-mcp");
    expect(launch).not.toContain("agent-history");
  });

  it("gives a view-only member the builder walk but not the publish stop", () => {
    // Instructions and the toolbox render for anyone who may view an agent;
    // Publish is agents:publish, which a Viewer lacks, so that stop drops. The
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
