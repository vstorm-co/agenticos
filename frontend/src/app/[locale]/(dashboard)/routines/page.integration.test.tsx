import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RoutinesPage from "./page";

let canCreate = true;
let canWatch = true;

vi.mock("@/hooks", () => ({
  useCanCreateTrigger: () => canCreate,
}));
// The list and the portal dialog have their own suites; stubbed here so the page's
// own job - the two create buttons and their gating - is what this suite checks.
vi.mock("@/components/runs/scheduled-tab", () => ({
  ScheduledTab: () => <div data-testid="scheduled-tab" />,
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({
    open,
    initialType,
    initialTemplate,
    onOpenChange,
  }: {
    open: boolean;
    initialType?: string;
    initialTemplate?: { key: string } | null;
    onOpenChange: (open: boolean) => void;
  }) =>
    open ? (
      <div
        role="dialog"
        aria-label={`schedule-dialog:${initialType}:${initialTemplate?.key ?? "blank"}`}
      >
        <button type="button" onClick={() => onOpenChange(false)}>
          close
        </button>
      </div>
    ) : null,
}));

vi.mock("@/components/watches/watches-card", () => ({
  useCanWatch: () => canWatch,
  WatchesCard: ({ onNew }: { onNew: () => void }) => (
    <button type="button" onClick={onNew}>
      watches-card
    </button>
  ),
}));
vi.mock("@/components/watches/watch-dialog", () => ({
  WatchDialog: ({ onOpenChange }: { onOpenChange: (open: boolean) => void }) => (
    <div role="dialog" aria-label="watch-dialog">
      <button type="button" onClick={() => onOpenChange(false)}>
        close watch
      </button>
    </div>
  ),
}));
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: ({ open }: { open: boolean }) =>
    open ? <div role="dialog" aria-label="event-dialog" /> : null,
}));

beforeEach(() => {
  canCreate = true;
  canWatch = true;
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

    expect(
      screen.getByRole("dialog", { name: "schedule-dialog:schedule:blank" }),
    ).toBeInTheDocument();
  });

  it("keeps the routines list without a separate recommendations panel", () => {
    render(<RoutinesPage />);
    expect(screen.queryByText("Ideas to start from")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New schedule" })).toBeInTheDocument();
  });

  it("opens the portal picker dialog from New event trigger", async () => {
    const user = userEvent.setup();
    render(<RoutinesPage />);

    await user.click(screen.getByRole("button", { name: "New event trigger" }));

    expect(screen.getByRole("dialog", { name: "event-dialog" })).toBeInTheDocument();
  });

  it("hides both create buttons from a caller who may not run an agent", async () => {
    // Runnability, not role: a caller with no runnable agent - none owned, none
    // shared with a run grant - reads `useCanCreateTrigger` false.
    canCreate = false;
    render(<RoutinesPage />);

    expect(screen.queryByRole("button", { name: "New schedule" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New event trigger" })).toBeNull();
    // The list still shows - viewing is not gated on running.
    expect(screen.getByTestId("scheduled-tab")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New watch" })).toBeNull();
    await userEvent.click(screen.getByRole("tab", { name: "My watches" }));
    expect(screen.getByRole("button", { name: "New watch" })).toBeInTheDocument();
    expect(screen.queryByTestId("scheduled-tab")).toBeNull();
  });

  it("starts a watch from the header or the card, and offers none where it cannot run", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<RoutinesPage />);

    await user.click(screen.getByRole("tab", { name: "My watches" }));
    expect(new URL(window.location.href).searchParams.get("tab")).toBe("watches");
    await user.click(screen.getByRole("button", { name: "New watch" }));
    expect(screen.getByRole("dialog", { name: "watch-dialog" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "close watch" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "watches-card" }));
    expect(screen.getByRole("dialog", { name: "watch-dialog" })).toBeInTheDocument();
    unmount();

    canWatch = false;
    canCreate = false;
    render(<RoutinesPage />);
    expect(screen.queryByRole("button", { name: "New watch" })).toBeNull();
  });
});

it("keeps the same page heading and description across both tabs", async () => {
  render(<RoutinesPage />);
  const description = screen.getByText(
    "Agent routines carry out tasks. My watches check your connected accounts and bring findings to your private Inbox.",
  );
  await userEvent.click(screen.getByRole("tab", { name: "My watches" }));
  expect(screen.getByRole("heading", { level: 1, name: "Routines" })).toBeInTheDocument();
  expect(description).toBeInTheDocument();
});
