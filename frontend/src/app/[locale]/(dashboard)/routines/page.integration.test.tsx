import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RoutinesPage from "./page";

let can: (permission: string) => boolean = () => true;

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can, isLoading: false }),
}));
// The list and the portal grid have their own suites; stubbed here so the page's
// own job - the Split New and its gating - is what this suite checks.
vi.mock("@/components/runs/scheduled-tab", () => ({
  ScheduledTab: () => <div data-testid="scheduled-tab" />,
}));
vi.mock("@/components/triggers/portals-tab", () => ({
  PortalsTab: () => <div data-testid="portals-tab" />,
}));
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="New event trigger" /> : null,
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({ open, initialType }: { open: boolean; initialType?: string }) =>
    open ? <div role="dialog" aria-label={`schedule-dialog:${initialType}`} /> : null,
}));

beforeEach(() => {
  can = () => true;
});

describe("RoutinesPage", () => {
  it("shows the org-wide list and the portal grid", () => {
    render(<RoutinesPage />);

    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
    expect(screen.getByTestId("portals-tab")).toBeInTheDocument();
  });

  it("opens the cadence form from New schedule", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New schedule" }));

    expect(screen.getByRole("dialog", { name: "schedule-dialog:schedule" })).toBeInTheDocument();
  });

  it("opens the portal grid from New event trigger", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New event trigger" }));

    expect(screen.getByRole("dialog", { name: "New event trigger" })).toBeInTheDocument();
  });

  it("hides the create buttons from a caller who may not run an agent", () => {
    can = (permission) => permission !== "agents:run";
    render(<RoutinesPage />);

    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New event trigger" })).toBeNull();
    // The list still shows - viewing is not gated on running.
    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
  });
});
