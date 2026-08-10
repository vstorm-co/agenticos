import { describe, expect, it } from "vitest";

import { TOUR_STEPS, visibleTourSteps } from "./tour";
import { Perm, type Permission } from "@/types/permissions";

describe("visibleTourSteps", () => {
  it("shows every step to a caller who can do everything", () => {
    expect(visibleTourSteps(() => true)).toEqual(TOUR_STEPS);
  });

  it("keeps only the ungated steps when the caller can do nothing", () => {
    // welcome, the dashboard tour, chat and the closing card carry no permission,
    // so they survive even a caller the server would refuse everywhere else.
    expect(visibleTourSteps(() => false).map((step) => step.id)).toEqual([
      "welcome",
      "dashboard",
      "chat",
      "finish",
    ]);
  });

  it("drops the pages a Viewer's permissions would have the server refuse", () => {
    const held = new Set<Permission>([Perm.agentsView, Perm.skillsView, Perm.collectionsView]);
    const ids = visibleTourSteps((permission) => held.has(permission)).map((step) => step.id);

    expect(ids).toEqual([
      "welcome",
      "dashboard",
      "chat",
      "agents",
      "skills",
      "knowledge",
      "finish",
    ]);
    expect(ids).not.toContain("activity");
    expect(ids).not.toContain("vault");
  });
});
