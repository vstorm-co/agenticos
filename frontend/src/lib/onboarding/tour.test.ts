import { describe, expect, it } from "vitest";

import { stepsForPage, TOUR_STEPS, visibleTourSteps } from "./tour";
import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

// The curated launch pass a caller with no permissions sees: the interstitials
// and the ungated highlights, in order. Every stop gated on a view or edit
// permission drops out.
const UNGATED_LAUNCH = [
  "welcome",
  "dashboard-actions",
  "dashboard-filters",
  "chat-start",
  "chat-agent-picker",
  "finish",
];

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

  it("skips the edit-gated build/knowledge/vault stops a view-only member cannot act on", () => {
    // The create buttons those steps point at are edit-gated, so a member who can
    // only view has no button to spotlight and the step is dropped — but MCP
    // servers rides on agents:view, so that one stop stays.
    const held = new Set<Permission>([Perm.agentsView, Perm.skillsView, Perm.collectionsView]);
    expect(visibleTourSteps((permission) => held.has(permission)).map((step) => step.id)).toEqual([
      "welcome",
      "dashboard-actions",
      "dashboard-filters",
      "chat-start",
      "chat-agent-picker",
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
  it("returns every highlight on the page — launch and '?'-only — never an interstitial", () => {
    expect(stepsForPage(ROUTES.CHAT, () => true).map((step) => step.id)).toEqual([
      "chat-start",
      "chat-agent-picker",
      "chat-composer",
      "chat-model-picker",
    ]);
  });

  it("is richer than the launch pass for the same page", () => {
    const onPage = stepsForPage(ROUTES.CHAT, () => true);
    const inLaunch = visibleTourSteps(() => true).filter((step) => step.page === ROUTES.CHAT);
    expect(onPage.length).toBeGreaterThan(inLaunch.length);
  });

  it("is permission-filtered the same way the tour is", () => {
    // agents-new is edit-gated, agents-filters is not — a caller who can do
    // nothing still gets the ungated highlight rather than an empty page.
    expect(stepsForPage(ROUTES.AGENTS, () => false).map((step) => step.id)).toEqual([
      "agents-filters",
    ]);
    expect(
      stepsForPage(ROUTES.AGENTS, (permission) => permission === Perm.agentsEdit).map(
        (step) => step.id,
      ),
    ).toEqual(["agents-new", "agents-filters"]);
  });

  it("is empty for a page the tour does not cover", () => {
    expect(stepsForPage(ROUTES.PROFILE, () => true)).toEqual([]);
  });
});
