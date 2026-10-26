import { beforeEach, describe, expect, it } from "vitest";

import { resetSessionState, resetTenantState } from "./session-reset";
import { useOnboardingStore } from "./onboarding-store";
import { useOrgStore } from "./org-store";
import { addVisualImages, useVisualImagesStore } from "./visual-stream-store";
import { useUnsavedChangesStore } from "./unsaved-changes-store";
import { copyKey, readCopies, writeCopy } from "@/lib/unsaved-copies";

describe("resetTenantState", () => {
  beforeEach(() => {
    useOnboardingStore.setState({
      isOpen: false,
      offer: null,
      flowId: null,
      flowAgentId: null,
      choices: {},
    });
  });

  it("forgets the unsaved edits kept in this browser, and stops asking about them", () => {
    writeCopy(copyKey("org-1", "ds-1", "grading"), 1, {});
    localStorage.setItem("theme", "dark");
    useUnsavedChangesStore.setState({ sources: { editor: { discard: () => {} } } });

    resetTenantState();

    expect(readCopies("org-1", "ds-1")).toEqual([]);
    expect(localStorage.getItem("theme")).toBe("dark");
    expect(useUnsavedChangesStore.getState().sources).toEqual({});
  });

  it("closes a running onboarding flow and clears a pending offer on an org switch", () => {
    // The flow built an agent in this organization and captured its id, and the
    // offer was minted from this org's caches. A flow left running across the
    // switch would route to the previous org's agent, so both must end here.
    const store = useOnboardingStore.getState();
    store.openFlow("create-agent");
    store.setFlowAgentId("a-1");
    store.openOffer("create-skill");
    expect(useOnboardingStore.getState().isOpen).toBe(true);
    expect(useOnboardingStore.getState().offer).toBe("create-skill");

    resetTenantState();

    expect(useOnboardingStore.getState().isOpen).toBe(false);
    expect(useOnboardingStore.getState().offer).toBeNull();
  });
});

describe("resetTenantState and visuals", () => {
  it("forgets the previous tenant's pictures, keyed by a call id the next may reuse", () => {
    addVisualImages("call_0", { logo: "data:previous-tenant" });

    resetTenantState();

    expect(useVisualImagesStore.getState().images).toEqual({});
  });
});

describe("resetSessionState", () => {
  it("also clears the organization selection and its recorded refusals", () => {
    useOrgStore.setState({ activeOrgId: "org-1", refusedOrgIds: ["org-2"] });

    resetSessionState();

    expect(useOrgStore.getState().activeOrgId).toBeNull();
    expect(useOrgStore.getState().refusedOrgIds).toEqual([]);
  });
});
