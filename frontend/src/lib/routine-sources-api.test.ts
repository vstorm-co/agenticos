import { expect, it, vi } from "vitest";
const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: client }));
import {
  routineSourceBlockers,
  routineSourcesApi,
  type RoutineSourceReview,
} from "./routine-sources-api";

it("reviews and accepts the exact routine through its owner-scoped endpoint", async () => {
  client.get.mockResolvedValue({ current: false });
  client.put.mockResolvedValue({ current: true });
  expect(await routineSourcesApi.get("agent", "routine")).toEqual({ current: false });
  expect(await routineSourcesApi.replace("agent", "routine", { review_token: "review" })).toEqual({
    current: true,
  });
  expect(client.get).toHaveBeenCalledWith("/agents/agent/triggers/routine/sources");
  expect(client.put).toHaveBeenCalledWith("/agents/agent/triggers/routine/sources", {
    review_token: "review",
  });
});

it("saves an explicit inheritance choice with its exact review token", async () => {
  client.put.mockResolvedValue({ current: true, mode: "follow_agent" });
  await routineSourcesApi.replace("agent", "routine", {
    review_token: "fresh",
    mode: "follow_agent",
  });
  expect(client.put).toHaveBeenLastCalledWith("/agents/agent/triggers/routine/sources", {
    review_token: "fresh",
    mode: "follow_agent",
  });
});

it.each([
  {
    mode: "follow_agent" as const,
    required: undefined,
    blocked: ["Required identity", "Optional mailbox"],
  },
  {
    mode: "follow_agent" as const,
    required: ["Required identity"],
    blocked: ["Required identity"],
  },
  { mode: "follow_agent" as const, required: [], blocked: [] },
  { mode: "restricted" as const, required: [], blocked: ["Required identity", "Optional mailbox"] },
])(
  "uses authoritative source blockers with conservative legacy fallback: %j",
  ({ mode, required, blocked }) => {
    const review: RoutineSourceReview = {
      current: false,
      review_token: "token",
      version_id: "v1",
      resources: [],
      accounts: [],
      unavailable_sources: ["Required identity", "Optional mailbox"],
      required_unavailable_sources: required,
    };
    expect(routineSourceBlockers(review, mode)).toEqual(blocked);
  },
);
