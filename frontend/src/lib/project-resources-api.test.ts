import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import {
  addProjectResources,
  listProjectResources,
  projectResourceCandidates,
  removeProjectResource,
  setProjectEntrypoint,
} from "./project-resources-api";
vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
beforeEach(() => vi.clearAllMocks());

it("walks the actual Apps endpoint beyond its first page", async () => {
  vi.mocked(apiClient.get)
    .mockResolvedValueOnce({ items: [{ id: "a", name: "One" }], total: 2 })
    .mockResolvedValueOnce({ items: [{ id: "b", name: "Two" }], total: 2 });
  expect(await projectResourceCandidates("app")).toHaveLength(2);
  expect(apiClient.get).toHaveBeenLastCalledWith("/apps", { params: { skip: "1", limit: "100" } });
});
it("keeps search and all link changes under the selected project", async () => {
  const ref = { kind: "agent", resource_id: "a" } as const;
  await listProjectResources("p", "research");
  expect(apiClient.get).toHaveBeenCalledWith("/projects/p/resources", {
    params: { q: "research" },
  });
  await addProjectResources("p", [ref]);
  expect(apiClient.post).toHaveBeenCalledWith("/projects/p/resources", { resources: [ref] });
  await removeProjectResource("p", ref);
  expect(apiClient.delete).toHaveBeenCalledWith("/projects/p/resources/agent/a");
  await setProjectEntrypoint("p", null);
  expect(apiClient.patch).toHaveBeenCalledWith("/projects/p/entrypoint", { workflow_id: null });
});
