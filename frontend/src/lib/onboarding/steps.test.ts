import { describe, expect, it } from "vitest";

import { ONBOARDING_STEPS, visibleOnboardingSteps } from "./steps";
import { Perm, type Permission } from "@/types/permissions";

const ids = (steps: readonly { id: string }[]) => steps.map((step) => step.id);

describe("visibleOnboardingSteps", () => {
  it("shows every step to a caller who can do everything", () => {
    expect(ids(visibleOnboardingSteps(() => true))).toEqual(ids(ONBOARDING_STEPS));
  });

  it("skips the steps a Viewer cannot act on", () => {
    // A Viewer holds exactly the three view permissions and nothing else, so
    // their tour must drop Activity (`runs:view`) and the Vault (`secrets:view`)
    // while keeping the pages they can reach.
    const held = new Set<Permission>([Perm.agentsView, Perm.skillsView, Perm.collectionsView]);
    const shown = ids(visibleOnboardingSteps((permission) => held.has(permission)));

    expect(shown).toContain("agents");
    expect(shown).toContain("skills");
    expect(shown).toContain("knowledge");
    expect(shown).not.toContain("activity");
    expect(shown).not.toContain("vault");
    // Welcome and finish carry no permission, so the walkthrough is never empty.
    expect(shown[0]).toBe("welcome");
    expect(shown.at(-1)).toBe("finish");
  });
});
