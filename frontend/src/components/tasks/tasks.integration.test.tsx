import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { Perm } from "@/types/permissions";
import { TasksPanel } from "./tasks-panel";
import { TaskBoardButton } from "./task-board-button";
const state = vi.hoisted(() => ({ permissions: new Set<string>(), push: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => "org",
  useTenantGuard: () => () => true,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (permission: string) => state.permissions.has(permission) }),
}));
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents: [], error: null }) }));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: Object.assign(
    (select: (value: { user: { id: string } }) => unknown) => select({ user: { id: "me" } }),
    { getState: () => ({ user: { id: "me" } }) },
  ),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: state.push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
        })
      }
    >
      {children}
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  state.permissions = new Set([Perm.tablesView, Perm.tablesCreate, Perm.tablesEdit]);
  vi.mocked(apiClient.get).mockResolvedValue([]);
  vi.mocked(apiClient.post).mockResolvedValue({ id: "task", table_id: "board" });
});
describe("durable tasks", () => {
  it("hides creation controls without the create permission", async () => {
    state.permissions.delete(Perm.tablesCreate);
    render(
      <>
        <TasksPanel />
        <TaskBoardButton scope="project" scopeId="project" />
      </>,
      { wrapper },
    );
    expect(await screen.findByText("No tasks here yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New task" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tasks" })).not.toBeInTheDocument();
  });
  it("saves a reminder separately from the deadline into its implicit private board", async () => {
    const user = userEvent.setup();
    render(<TasksPanel />, { wrapper });
    await user.click(screen.getByRole("button", { name: "New task" }));
    await user.type(screen.getByLabelText("Task", { exact: true }), "Send approved reply");
    fireEvent.change(screen.getByLabelText("Start at", { exact: true }), {
      target: { value: "2026-12-01T09:00" },
    });
    fireEvent.change(screen.getByLabelText("Due at", { exact: true }), {
      target: { value: "2026-12-02T17:00" },
    });
    await user.click(screen.getByRole("button", { name: "Create task" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/tasks",
        expect.objectContaining({
          title: "Send approved reply",
          assignee_user_id: "me",
          assignee_agent_id: null,
          scope: "private",
          start_at: new Date("2026-12-01T09:00").toISOString(),
          due_at: new Date("2026-12-02T17:00").toISOString(),
        }),
      ),
    );
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
  it("provisions and opens the project table", async () => {
    const user = userEvent.setup();
    render(<TaskBoardButton scope="project" scopeId="project-id" />, { wrapper });
    await user.click(screen.getByRole("button", { name: "Tasks" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/tasks/boards", {
        scope: "project",
        scope_id: "project-id",
      }),
    );
    await waitFor(() => expect(state.push).toHaveBeenCalledWith("/tables/board"));
  });
  it("shows a query failure instead of an empty state", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Unavailable"));
    render(<TasksPanel />, { wrapper });
    expect(await screen.findByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("No tasks here yet")).not.toBeInTheDocument();
  });
});
