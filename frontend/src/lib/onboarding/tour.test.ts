import { describe, expect, it } from "vitest";

import { stepsForPage, TOUR_STEPS, visibleTourSteps } from "./tour";
import { ROUTES } from "@/lib/constants";
import { Perm, type Permission } from "@/types/permissions";

const UNGATED = ["welcome", "dashboard-actions", "dashboard-filters", "chat-start", "finish"];

describe("visibleTourSteps", () => {
  it("shows every step to a caller who can do everything", () => {
    expect(visibleTourSteps(() => true)).toEqual(TOUR_STEPS);
  });

  it("keeps only the ungated steps when the caller can do nothing", () => {
    expect(visibleTourSteps(() => false).map((step) => step.id)).toEqual(UNGATED);
  });

  it("skips the build/knowledge/vault stops a view-only member cannot act on", () => {
    // The create buttons those steps point at are edit-gated, so a member who can
    // only view has no button to spotlight — the step is dropped rather than left
    // hunting an element that will never render.
    const held = new Set<Permission>([Perm.agentsView, Perm.skillsView, Perm.collectionsView]);
    expect(visibleTourSteps((permission) => held.has(permission)).map((step) => step.id)).toEqual(
      UNGATED,
    );
  });

  it("includes a stop once the caller holds the permission its target needs", () => {
    const ids = visibleTourSteps((permission) => permission === Perm.agentsEdit).map(
      (step) => step.id,
    );
    expect(ids).toContain("agents-new");
  });
});

describe("stepsForPage", () => {
  it("returns only the highlights that live on that page, never the interstitials", () => {
    expect(stepsForPage(ROUTES.DASHBOARD, () => true).map((step) => step.id)).toEqual([
      "dashboard-actions",
      "dashboard-filters",
    ]);
  });

  it("is permission-filtered the same way the tour is", () => {
    expect(stepsForPage(ROUTES.AGENTS, () => false)).toEqual([]);
    expect(
      stepsForPage(ROUTES.AGENTS, (permission) => permission === Perm.agentsEdit).map(
        (step) => step.id,
      ),
    ).toEqual(["agents-new"]);
  });

  it("is empty for a page the tour does not cover", () => {
    expect(stepsForPage(ROUTES.ORGS, () => true)).toEqual([]);
  });
});
