import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useProjectResources, useProjectResourceCandidates } from "./use-project-resources";
import * as api from "@/lib/project-resources-api";
import { qk } from "@/lib/query-keys";
vi.mock("@/lib/project-resources-api", () => ({
  listProjectResources: vi.fn(),
  addProjectResources: vi.fn(),
  removeProjectResource: vi.fn(),
  setProjectEntrypoint: vi.fn(),
  projectResourceCandidates: vi.fn(),
}));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listProjectResources).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.addProjectResources).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.setProjectEntrypoint).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.removeProjectResource).mockResolvedValue(undefined);
  vi.mocked(api.projectResourceCandidates).mockResolvedValue([]);
});
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
it("refreshes project and registry filters after every membership change", async () => {
  const { client, wrapper } = setup();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const { result } = renderHook(() => useProjectResources("p", "query"), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(api.listProjectResources).toHaveBeenCalledWith("p", "query");
  const ref = { kind: "agent", resource_id: "a" } as const;
  await act(async () => {
    await result.current.add.mutateAsync([ref]);
  });
  await act(async () => {
    await result.current.remove.mutateAsync(ref);
  });
  await act(async () => {
    await result.current.entrypoint.mutateAsync(null);
  });
  expect(api.addProjectResources).toHaveBeenCalledWith("p", [ref]);
  expect(api.removeProjectResource).toHaveBeenCalledWith("p", ref);
  expect(api.setProjectEntrypoint).toHaveBeenCalledWith("p", null);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.projects.detail("p") });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.workflows.all() });
});
it("does not fetch a candidate catalog until the permission-gated picker opens", async () => {
  const { wrapper } = setup();
  const { result, rerender } = renderHook(
    ({ enabled }) => useProjectResourceCandidates("workflow", enabled),
    { wrapper, initialProps: { enabled: false } },
  );
  expect(api.projectResourceCandidates).not.toHaveBeenCalled();
  rerender({ enabled: true });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(api.projectResourceCandidates).toHaveBeenCalledWith("workflow");
});
