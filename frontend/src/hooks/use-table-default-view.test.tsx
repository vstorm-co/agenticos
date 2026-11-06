import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useTableDefaultView } from "./use-table-views";
import { createView, updateView } from "@/lib/table-views-api";
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
    await result.current.mutateAsync({
      view: null,
      kind: "kanban",
      config,
      names: ["Default kanban", "Default kanban 2"],
    });
  });
  expect(createView).toHaveBeenCalledWith(
    "tasks",
    expect.objectContaining({
      name: "Default kanban 3",
      kind: "kanban",
      visibility: "shared",
      config,
    }),
  );
  expect(updateTable).toHaveBeenCalledWith("tasks", { default_view_id: "kanban-view" });
});

it("copies another owner's view rather than discarding the current grouping", async () => {
  const source = {
    id: "someone-elses-view",
    table_id: "tasks",
    owner_user_id: "other",
    name: "Board",
    kind: "kanban" as const,
    visibility: "shared" as const,
    config: emptyViewConfig(),
    can_manage: false,
    can_delete: false,
    created_at: "2026-11-05T00:00:00Z",
    updated_at: null,
  };
  vi.mocked(createView).mockResolvedValue({ ...source, id: "copy" });
  const { result } = renderHook(() => useTableDefaultView("tasks"), { wrapper });
  const config = { ...emptyViewConfig(), group_by: "priority" };
  await act(async () => {
    await result.current.mutateAsync({ view: source, kind: "kanban", config, names: [] });
  });
  expect(updateView).not.toHaveBeenCalled();
  expect(createView).toHaveBeenCalledWith(
    "tasks",
    expect.objectContaining({ config, visibility: "shared" }),
  );
  expect(updateTable).toHaveBeenCalledWith("tasks", { default_view_id: "copy" });
});

it("keeps a refused default-view update visible instead of reporting success", async () => {
  vi.mocked(createView).mockRejectedValue(new Error("Table permissions changed"));
  const { result } = renderHook(() => useTableDefaultView("tasks"), { wrapper });
  await act(async () => {
    await result.current
      .mutateAsync({ view: null, kind: "kanban", config: emptyViewConfig(), names: [] })
      .catch(() => undefined);
  });
  expect(toast.error).toHaveBeenCalled();
  expect(updateTable).not.toHaveBeenCalled();
});
