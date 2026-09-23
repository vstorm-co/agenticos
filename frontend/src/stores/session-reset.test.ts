import { beforeEach, describe, expect, it } from "vitest";

import { resetSessionState, resetTenantState } from "./session-reset";
import { useOnboardingStore } from "./onboarding-store";
import { useOrgStore } from "./org-store";
import { useTableViewStore } from "./table-view-store";

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

  it("drops a conflict banner naming a record from the previous organization", () => {
    useTableViewStore.getState().setConflict({
      recordId: "rec-1",
      pendingValues: { "col-1": "x" },
      fieldId: "col-1",
    });
    expect(useTableViewStore.getState().conflicts["rec-1"]).toBeDefined();

    resetTenantState();

    expect(useTableViewStore.getState().conflicts).toEqual({});
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
