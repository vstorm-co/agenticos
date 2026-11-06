import { expect, it, vi } from "vitest";
const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: client }));
import { routineSourcesApi } from "./routine-sources-api";

it("reviews and accepts the exact routine through its owner-scoped endpoint", async () => {
  client.get.mockResolvedValue({ current: false });
  client.put.mockResolvedValue({ current: true });
  expect(await routineSourcesApi.get("agent", "routine")).toEqual({ current: false });
  expect(await routineSourcesApi.replace("agent", "routine", "review")).toEqual({ current: true });
  expect(client.get).toHaveBeenCalledWith("/agents/agent/triggers/routine/sources");
  expect(client.put).toHaveBeenCalledWith("/agents/agent/triggers/routine/sources", {
    review_token: "review",
  });
});
