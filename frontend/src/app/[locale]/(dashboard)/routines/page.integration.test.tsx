import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RoutinesPage from "./page";

let canCreate = true;

vi.mock("@/hooks", () => ({
  useCanCreateTrigger: () => canCreate,
}));
// The list and the portal dialog have their own suites; stubbed here so the page's
// own job - the two create buttons and their gating - is what this suite checks.
vi.mock("@/components/runs/scheduled-tab", () => ({
  ScheduledTab: () => <div data-testid="scheduled-tab" />,
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({ open, initialType }: { open: boolean; initialType?: string }) =>
    open ? <div role="dialog" aria-label={`schedule-dialog:${initialType}`} /> : null,
}));
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="event-dialog" /> : null,
}));

beforeEach(() => {
  canCreate = true;
});

describe("RoutinesPage", () => {
  it("shows the org-wide list and both create buttons, and no portal grid inline", () => {
    render(<RoutinesPage />);

    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New schedule" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New event trigger" })).toBeInTheDocument();
  });

  it("opens the cadence form from New schedule", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New schedule" }));

    expect(screen.getByRole("dialog", { name: "schedule-dialog:schedule" })).toBeInTheDocument();
  });

  it("opens the portal picker dialog from New event trigger", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New event trigger" }));

    expect(screen.getByRole("dialog", { name: "event-dialog" })).toBeInTheDocument();
  });

  it("hides both create buttons from a caller who may not run an agent", () => {
    // Runnability, not role: a caller with no runnable agent - none owned, none
    // shared with a run grant - reads `useCanCreateTrigger` false.
    canCreate = false;
    render(<RoutinesPage />);

    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New event trigger" })).toBeNull();
    // The list still shows - viewing is not gated on running.
    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
  });
});
