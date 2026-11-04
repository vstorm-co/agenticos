import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { RoutinesList } from "./routines-list";

const state = vi.hoisted(() => ({ error: null as Error | null, loading: false }));
vi.mock("@/hooks/use-org-triggers", () => ({
  useOrgTriggers: () => ({
    triggers: [{ id: "task", name: "Weekly report", prompt: "Summarize invoices" }],
    error: state.error,
    isLoading: state.loading,
  }),
}));
vi.mock("@/hooks/use-watches", () => ({
  useWatches: () => ({
    watches: [{ id: "monitor", title: "Client mail", instructions: "Find urgent mail" }],
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
