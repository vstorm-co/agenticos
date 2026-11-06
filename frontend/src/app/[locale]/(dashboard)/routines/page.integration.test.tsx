import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RoutinesPage from "./page";

const state = vi.hoisted(() => ({ create: true, monitor: true }));
vi.mock("@/hooks", () => ({ useCanCreateTrigger: () => state.create }));
vi.mock("@/components/triggers/routines-list", () => ({
  RoutinesList: () => <div data-testid="all-routines" />,
}));
vi.mock("@/components/watches/watches-card", () => ({ useCanWatch: () => state.monitor }));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: () => <div role="dialog" aria-label="schedule" />,
}));
vi.mock("@/components/triggers/new-event-trigger-dialog", () => ({
  NewEventTriggerDialog: () => <div role="dialog" aria-label="event" />,
}));
vi.mock("@/components/watches/watch-dialog", () => ({
  WatchDialog: () => <div role="dialog" aria-label="monitor" />,
}));
beforeEach(() => {
  state.create = true;
  state.monitor = true;
});

describe("RoutinesPage", () => {
  it("shows one list without separate agent and watch tabs", () => {
    render(<RoutinesPage />);
    expect(screen.getByTestId("all-routines")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.getByRole("button", { name: "New routine" })).toBeVisible();
  });
  it.each([
    ["Run on a schedule", "schedule"],
    ["Run when an event arrives", "event"],
    ["Monitor and inform", "monitor"],
  ])("starts %s from one create menu", async (label, dialog) => {
    render(<RoutinesPage />);
    await userEvent.click(screen.getByRole("button", { name: "New routine" }));
    await userEvent.click(screen.getByRole("menuitem", { name: label }));
    expect(screen.getByRole("dialog", { name: dialog })).toBeVisible();
  });
  it("offers monitoring independently of agent task creation", async () => {
    state.create = false;
    render(<RoutinesPage />);
    await userEvent.click(screen.getByRole("button", { name: "New routine" }));
    expect(screen.queryByRole("menuitem", { name: "Run on a schedule" })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Monitor and inform" })).toBeVisible();
  });
  it("hides monitoring when unavailable and hides creation when neither is allowed", async () => {
    state.monitor = false;
    const { unmount } = render(<RoutinesPage />);
    await userEvent.click(screen.getByRole("button", { name: "New routine" }));
    expect(screen.queryByRole("menuitem", { name: "Monitor and inform" })).toBeNull();
    unmount();
    state.create = false;
    render(<RoutinesPage />);
    expect(screen.queryByRole("button", { name: "New routine" })).toBeNull();
    expect(screen.getByTestId("all-routines")).toBeInTheDocument();
  });
});
