import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { RoutinesList } from "./routines-list";

const state = vi.hoisted(() => ({
  error: null as Error | null,
  loading: false,
  refetchTasks: vi.fn(),
  refetchWatches: vi.fn(),
}));
vi.mock("@/hooks/use-org-triggers", () => ({
  useOrgTriggers: () => ({
    triggers: [{ id: "task", name: "Weekly report", prompt: "Summarize invoices" }],
    refetch: state.refetchTasks,
    error: state.error,
    isLoading: state.loading,
  }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatches: () => ({
    watches: [{ id: "monitor", title: "Client mail", instructions: "Find urgent mail" }],
    refetch: state.refetchWatches,
    isLoading: false,
    error: null,
  }),
}));
vi.mock("@/hooks", () => ({ useMcpConnections: () => ({ connections: [] }) }));
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
});

it("lists scheduled tasks and monitoring in the same searchable list", async () => {
  render(<RoutinesList />);
  expect(screen.getByText("Weekly report")).toBeVisible();
  expect(screen.getByText("Client mail")).toBeVisible();
  expect(screen.getByText("2 routines")).toBeVisible();
  await userEvent.type(screen.getByPlaceholderText("Search routines"), "urgent");
  expect(screen.getByText("Client mail")).toBeVisible();
  expect(screen.queryByText("Weekly report")).toBeNull();
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
  await userEvent.click(screen.getByText("Clear search", { selector: "button" }));
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
