import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useTableDefaultView } from "./use-table-views";
import { createView } from "@/lib/table-views-api";
import { updateTable } from "@/lib/tables-api";
import { emptyViewConfig } from "@/types/tables";
vi.mock("@/lib/table-views-api", () => ({
  createView: vi.fn(),
  updateView: vi.fn(),
  listViews: vi.fn(),
  deleteView: vi.fn(),
}));
vi.mock("@/lib/tables-api", () => ({ updateTable: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}
    >
      {children}
    </QueryClientProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
});
it("saves the current Kanban as a shared view and sets that exact view as the table default", async () => {
  vi.mocked(createView).mockResolvedValue({
    id: "kanban-view",
    table_id: "tasks",
    owner_user_id: "owner",
    name: "Board",
    kind: "kanban",
    visibility: "shared",
    config: emptyViewConfig(),
    can_manage: true,
    can_delete: true,
    created_at: "2026-11-05T00:00:00Z",
    updated_at: null,
  });
  const { result } = renderHook(() => useTableDefaultView("tasks"), { wrapper });
  const config = { ...emptyViewConfig(), group_by: "status-column" };
  await act(async () => {
    await result.current.mutateAsync({ view: null, kind: "kanban", config, names: [] });
  });
  expect(createView).toHaveBeenCalledWith(
    "tasks",
    expect.objectContaining({ kind: "kanban", visibility: "shared", config }),
  );
  expect(updateTable).toHaveBeenCalledWith("tasks", { default_view_id: "kanban-view" });
});
