import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreationOffer } from "./creation-offer";
import { useOnboardingStore } from "@/stores/onboarding-store";
import type { Permission } from "@/types/permissions";

const rig = vi.hoisted(() => ({ can: (_permission: Permission): boolean => true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: rig.can, isLoading: false, error: null }),
}));

beforeEach(() => {
  rig.can = () => true;
  useOnboardingStore.setState({ isOpen: false, index: 0, mode: "tour", flowId: null, offer: null });
});

describe("CreationOffer", () => {
  it("offers the flow the store names, and accepting starts it", async () => {
    useOnboardingStore.setState({ offer: "create-skill" });
    render(<CreationOffer />);
    expect(screen.getByText("Create a skill?")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Yes, guide me" }));
    expect(useOnboardingStore.getState()).toMatchObject({
      isOpen: true,
      mode: "flow",
      flowId: "create-skill",
      offer: null,
    });
  });

  it("declining records nothing but clearing the prompt", async () => {
    useOnboardingStore.setState({ offer: "create-kb" });
    render(<CreationOffer />);
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(useOnboardingStore.getState()).toMatchObject({
      offer: null,
      mode: "tour",
      isOpen: false,
    });
  });

  it("makes no offer the caller may not act on", () => {
    rig.can = () => false;
    useOnboardingStore.setState({ offer: "create-skill" });
    render(<CreationOffer />);
    expect(screen.queryByText("Create a skill?")).toBeNull();
  });

  it("offers an unpermissioned create to anyone", () => {
    rig.can = () => false;
    useOnboardingStore.setState({ offer: "create-org" });
    render(<CreationOffer />);
    expect(screen.getByText("Create an organization?")).toBeInTheDocument();
  });

  it("renders nothing when there is no offer", () => {
    const { container } = render(<CreationOffer />);
    expect(container).toBeEmptyDOMElement();
  });
});
