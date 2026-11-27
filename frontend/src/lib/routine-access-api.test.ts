import { beforeEach, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: client }));

import {
  mayRunFreely,
  routineAccessApi,
  routineToolIdentity,
  routineToolKey,
  shownSetting,
  type RoutineToolOption,
} from "./routine-access-api";

const capability: RoutineToolOption = {
  capability_id: "mail",
  capability_name: "Mail",
  tool_id: "send",
  name: "send",
  effect: true,
  agent: "free",
  setting: null,
};
const mcp: RoutineToolOption = {
  connection_id: "c1",
  tool_id: "create_issue",
  name: "create_issue",
  account_name: "GitHub",
  account_scope: "organization",
  effect: true,
  agent: "free",
  setting: "allow",
};
const platform: RoutineToolOption = {
  kind: "platform",
  tool_id: "list_tasks",
  name: "list_tasks",
  group: "tasks",
  effect: false,
  agent: "free",
  setting: null,
};

beforeEach(() => vi.clearAllMocks());

it("reads and replaces a routine's access review through its one endpoint", async () => {
  client.get.mockResolvedValue({ current: false });
  client.put.mockResolvedValue({ current: true });
  expect(await routineAccessApi.get("agent", "routine")).toEqual({ current: false });
  const update = {
    review_token: "token",
    mode: "reviewed" as const,
    tools: [{ ...routineToolKey(capability), setting: "ask" as const }],
    delegates: "ask" as const,
  };
  expect(await routineAccessApi.replace("agent", "routine", update)).toEqual({ current: true });
  expect(client.get).toHaveBeenCalledWith("/agents/agent/triggers/routine/access");
  expect(client.put).toHaveBeenCalledWith("/agents/agent/triggers/routine/access", update);
});

it("names each kind of tool by its key alone, never by its display fields", () => {
  expect(routineToolKey(capability)).toEqual({ capability_id: "mail", tool_id: "send" });
  expect(routineToolKey(mcp)).toEqual({ connection_id: "c1", tool_id: "create_issue" });
  expect(routineToolKey(platform)).toEqual({ kind: "platform", tool_id: "list_tasks" });
  expect(JSON.parse(routineToolIdentity(mcp))).toEqual(routineToolKey(mcp));
});

it("shows a tool new since the review as the server treats it", () => {
  expect(shownSetting(capability)).toBe("ask");
  expect(shownSetting(platform)).toBe("allow");
  expect(shownSetting({ ...platform, agent: "ask" })).toBe("ask");
  expect(shownSetting(mcp)).toBe("allow");
});

it("lets a tool run freely only where the agent does and, for a change, the caller may", () => {
  expect(mayRunFreely(capability, true)).toBe(true);
  expect(mayRunFreely(capability, false)).toBe(false);
  expect(mayRunFreely(platform, false)).toBe(true);
  expect(mayRunFreely({ ...platform, agent: "ask" }, true)).toBe(false);
});
