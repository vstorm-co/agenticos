import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import type { ProjectTrackingCreate } from "@/lib/project-tracking-api";
import { qk } from "@/lib/query-keys";
const api = vi.hoisted(() => ({ get: vi.fn(), create: vi.fn(), review: vi.fn() }));
vi.mock("@/lib/project-tracking-api", () => ({ projectTrackingApi: api }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));
import { useProjectTracking, useProjectTrackingReview } from "./use-project-tracking";
const input: ProjectTrackingCreate = {
  base_agent_id: "agent",
  base_version_id: "v1",
  source_review_token: "review",
  publish_and_start: true,
  agent_name: "Tracker",
  table_name: "Tasks",
  table_visibility: "private",
  interval_seconds: 86400,
};
beforeEach(() => {
  api.get.mockReset().mockResolvedValue(null);
  api.create.mockReset();
  api.review.mockReset().mockResolvedValue({ review_token: "review" });
});
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
it("stores the idempotent installation and refreshes its existing product surfaces", async () => {
  const { client, wrapper } = setup();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  api.create.mockResolvedValue({ id: "setup", table_id: "tasks" });
  const { result } = renderHook(() => useProjectTracking("project"), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await result.current.create.mutateAsync(input);
  });
  expect(client.getQueryData(qk.projects.tracking("project"))).toEqual({
    id: "setup",
    table_id: "tasks",
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.triggers.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.tables.all() });
});
it("refreshes both installed state and source review after an ambiguous or stale submission", async () => {
  const { client, wrapper } = setup();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  api.create.mockRejectedValue(new Error("Changed"));
  const { result } = renderHook(() => useProjectTracking("project"), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await expect(result.current.create.mutateAsync(input)).rejects.toThrow("Changed");
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.projects.trackingReviews("project") });
  expect(api.get.mock.calls.length).toBeGreaterThan(1);
});
it("does not review without a pinned selection and fetches again when that version changes", async () => {
  const { wrapper } = setup();
  const initialSelection: { agent: string | null; version: string | null } = {
    agent: null,
    version: null,
  };
  const { result, rerender } = renderHook(
    ({ agent, version }: { agent: string | null; version: string | null }) =>
      useProjectTrackingReview("project", agent, version),
    { wrapper, initialProps: initialSelection },
  );
  expect(api.review).not.toHaveBeenCalled();
  rerender({ agent: "agent", version: null });
  expect(api.review).not.toHaveBeenCalled();
  rerender({ agent: "agent", version: "v1" });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(api.review).toHaveBeenLastCalledWith("project", "agent", "v1");
  rerender({ agent: "agent", version: "v2" });
  await waitFor(() => expect(api.review).toHaveBeenLastCalledWith("project", "agent", "v2"));
});
