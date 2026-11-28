import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { RoutinesList } from "./routines-list";

const state = vi.hoisted(() => ({
  error: null as Error | null,
  loading: false,
  empty: false,
  watchError: null as Error | null,
  refetchTasks: vi.fn(),
  refetchWatches: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));
vi.mock("@/hooks/use-org-triggers", () => ({
  useOrgTriggers: () => ({
    triggers: state.empty
      ? []
      : [{ id: "task", name: "Weekly report", prompt: "Summarize invoices" }],
    refetch: state.refetchTasks,
    error: state.error,
    isLoading: state.loading,
  }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatches: () => ({
    watches: state.empty
      ? []
      : [{ id: "monitor", title: "Client mail", instructions: "Find urgent mail" }],
    refetch: state.refetchWatches,
    isLoading: false,
    error: state.watchError,
  }),
}));
vi.mock("@/hooks", () => ({ useMcpConnections: () => ({ connections: [] }) }));
// One readiness read for the routines shown; the rows themselves are stubbed here.
const readiness = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-routine-readiness", () => ({
  useRoutinesReadiness: (triggers: { id: string }[]) => {
    readiness(triggers.map((trigger) => trigger.id));
    return () => [];
  },
}));
vi.mock("./trigger-row", () => ({
  TriggerRow: ({ trigger }: { trigger: { name: string } }) => <span>{trigger.name}</span>,
}));
vi.mock("@/components/watches/watches-card", () => ({
  WatchRow: ({ watch }: { watch: { title: string } }) => <li>{watch.title}</li>,
}));
vi.mock("@/components/watches/watch-dialog", () => ({ WatchDialog: () => null }));
beforeEach(() => {
  state.error = null;
  state.loading = false;
  state.empty = false;
  state.watchError = null;
  state.refetchTasks.mockClear();
  state.refetchWatches.mockClear();
});
afterEach(() => window.history.replaceState(null, "", "/"));
it("offers the way to start a routine inside the empty list", async () => {
  state.empty = true;
  const onClick = vi.fn();
  render(<RoutinesList emptyAction={{ label: "Run on a schedule", onClick }} />);
  expect(screen.getByText("No agent routines yet")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Run on a schedule" }));
  expect(onClick).toHaveBeenCalledOnce();
});
it("offers nothing in the empty list to somebody who may not start a routine", () => {
  state.empty = true;
  render(<RoutinesList />);
  expect(screen.getByText("No agent routines yet")).toBeVisible();
  expect(screen.queryByRole("button")).toBeNull();
});

it("lists scheduled tasks and monitoring in the same searchable list", async () => {
  render(<RoutinesList />);
  expect(screen.getByText("Weekly report")).toBeVisible();
  expect(screen.getByText("Client mail")).toBeVisible();
  expect(screen.getByText("2 routines")).toBeVisible();
  // Readiness is asked for the scheduled tasks on screen, never for a monitor.
  expect(readiness).toHaveBeenLastCalledWith(["task"]);
  await userEvent.type(screen.getByPlaceholderText("Search routines"), "urgent");
  expect(screen.getByText("Client mail")).toBeVisible();
  expect(screen.queryByText("Weekly report")).toBeNull();
});

it("shows only the linked routine and can clear its URL filter", async () => {
  window.history.replaceState(null, "", "/routines?routine=task");
  const { rerender } = render(<RoutinesList />);
  expect(screen.getByText("Weekly report")).toBeVisible();
  expect(screen.queryByText("Client mail")).toBeNull();
  expect(screen.getByText("1 routine")).toBeVisible();

  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(window.location.search).toBe("");
  rerender(<RoutinesList />);
  expect(screen.getByText("Client mail")).toBeVisible();
});

it("does not show a watch or other routine when the linked routine is unavailable", () => {
  window.history.replaceState(null, "", "/routines?routine=monitor");
  render(<RoutinesList />);
  expect(screen.getByText("No routine matches that.")).toBeVisible();
  expect(screen.queryByText("Weekly report")).toBeNull();
  expect(screen.queryByText("Client mail")).toBeNull();
});

it("keeps a linked routine visible when the unrelated watches read fails", () => {
  window.history.replaceState(null, "", "/routines?routine=task");
  state.watchError = new Error("Watches unavailable");
  render(<RoutinesList />);
  expect(screen.getByText("Weekly report")).toBeVisible();
});

it("retries only the tasks read after the linked routine fails to load", async () => {
  window.history.replaceState(null, "", "/routines?routine=task");
  state.error = new Error("Unavailable");
  render(<RoutinesList />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetchTasks).toHaveBeenCalledOnce();
  expect(state.refetchWatches).not.toHaveBeenCalled();
});
it("shows a read failure instead of presenting an incomplete list as complete", () => {
  state.error = new Error("Unavailable");
  render(<RoutinesList />);
  expect(screen.queryByText("Client mail")).toBeNull();
  expect(screen.queryByText("2 routines")).toBeNull();
});

it("loads as routine rows instead of a table with an unrelated header", () => {
  state.loading = true;
  render(<RoutinesList />);
  const loading = screen.getByRole("status", { name: "Loading" });
  expect(loading).toBeVisible();
  expect(loading.querySelector("table")).toBeNull();
  expect(loading.children).toHaveLength(4);
  expect(loading.querySelectorAll(".rounded-xl")).toHaveLength(4);
  expect(screen.queryByText("Weekly report")).not.toBeInTheDocument();
});

it("clears an empty search and restores both kinds of routine", async () => {
  render(<RoutinesList />);
  await userEvent.type(screen.getByPlaceholderText("Search routines"), "nothing-matches");
  expect(screen.getByText("No routine matches that.")).toBeVisible();
  expect(screen.queryByText(/0 of 2 routines/)).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
  expect(screen.getByPlaceholderText("Search routines")).toHaveValue("");
  expect(screen.getByText("Weekly report")).toBeVisible();
  expect(screen.getByText("Client mail")).toBeVisible();
});

it("retries both reads after the combined list fails", async () => {
  state.error = new Error("Unavailable");
  render(<RoutinesList />);
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.refetchTasks).toHaveBeenCalledTimes(1);
  expect(state.refetchWatches).toHaveBeenCalledTimes(1);
});

it("keeps search mounted and editable through a cold list load", async () => {
  state.empty = true;
  state.loading = true;
  const user = userEvent.setup();
  const { rerender } = render(<RoutinesList />);
  const search = screen.getByPlaceholderText("Search routines");
  await user.type(search, "report");
  expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
  state.empty = false;
  state.loading = false;
  rerender(<RoutinesList />);
  expect(screen.getByPlaceholderText("Search routines")).toBe(search);
  expect(search).toHaveValue("report");
  expect(screen.getByText("Weekly report")).toBeVisible();
  expect(screen.queryByText("Client mail")).not.toBeInTheDocument();
});
