import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RoutinesPage from "./page";

let canCreate = true;

vi.mock("@/hooks", () => ({
  useCanCreateTrigger: () => canCreate,
}));
// The list and the portal grid have their own suites; stubbed here so the page's
// own job - the Split New and its gating - is what this suite checks.
vi.mock("@/components/runs/scheduled-tab", () => ({
  ScheduledTab: () => <div data-testid="scheduled-tab" />,
}));
vi.mock("@/components/triggers/portals-tab", () => ({
  PortalsTab: () => <div data-testid="portals-tab" />,
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({ open, initialType }: { open: boolean; initialType?: string }) =>
    open ? <div role="dialog" aria-label={`schedule-dialog:${initialType}`} /> : null,
}));

beforeEach(() => {
  canCreate = true;
});

describe("RoutinesPage", () => {
  it("shows the org-wide list, and the portal grid inline as the event path", () => {
    render(<RoutinesPage />);

    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
    // The grid is the event-creation path here, so there is no separate "New
    // event trigger" button (unlike the agent panel and the sidebar).
    expect(screen.getByTestId("portals-tab")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New event trigger" })).toBeNull();
  });

  it("opens the cadence form from New schedule", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New schedule" }));

    expect(screen.getByRole("dialog", { name: "schedule-dialog:schedule" })).toBeInTheDocument();
  });

  it("hides the New schedule button from a caller who may not run an agent", () => {
    // Runnability, not role: a caller with no runnable agent - none owned, none
    // shared with a run grant - reads `useCanCreateTrigger` false.
    canCreate = false;
    render(<RoutinesPage />);

    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
    // The list and the grid still show - viewing is not gated on running.
    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
    expect(screen.getByTestId("portals-tab")).toBeInTheDocument();
  });
});
