import { expect, it, vi } from "vitest";
import type { ProjectTrackingCreate } from "./project-tracking-api";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: api }));
import { projectTrackingApi } from "./project-tracking-api";
it("keeps installation and source review scoped to the selected project and pinned version", async () => {
  api.get.mockResolvedValue(null);
  api.post.mockResolvedValue({ id: "installed" });
  await projectTrackingApi.get("project");
  await projectTrackingApi.review("project", "agent", "version");
  const input: ProjectTrackingCreate = {
    base_agent_id: "agent",
    base_version_id: "version",
    source_review_token: "review",
    publish_and_start: true,
    agent_name: "Tracker",
    table_name: "Tasks",
    table_visibility: "private",
    interval_seconds: 86400,
  };
  expect(await projectTrackingApi.create("project", input)).toEqual({ id: "installed" });
  expect(api.get).toHaveBeenNthCalledWith(1, "/projects/project/tracking");
  expect(api.get).toHaveBeenNthCalledWith(2, "/projects/project/tracking/review", {
    params: { base_agent_id: "agent", base_version_id: "version" },
  });
  expect(api.post).toHaveBeenCalledWith("/projects/project/tracking", input);
});
