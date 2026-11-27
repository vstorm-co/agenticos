import { beforeEach, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: client }));

import {
  mayRunFreely,
  routineAccessApi,
  routineToolIdentity,
  routineToolKey,
  modeDefault,
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
  effective: "ask",
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
  effective: "consent",
};
const platform: RoutineToolOption = {
  kind: "platform",
  tool_id: "list_tasks",
  name: "list_tasks",
  group: "tasks",
  effect: false,
  agent: "free",
  setting: null,
  effective: "run",
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

it("shows a tool without a setting of its own as its mode treats it", () => {
  expect(modeDefault(capability, "reviewed")).toBe("ask");
  expect(modeDefault(platform, "reviewed")).toBe("allow");
  expect(modeDefault(capability, "trust_agent")).toBe("allow");
  expect(modeDefault({ ...platform, agent: "ask" }, "trust_agent")).toBe("ask");
});

it("lets a tool run freely only where the agent does and, for a reviewed change, the caller may", () => {
  expect(mayRunFreely(capability, true, "reviewed")).toBe(true);
  expect(mayRunFreely(capability, false, "reviewed")).toBe(false);
  expect(mayRunFreely(platform, false, "reviewed")).toBe(true);
  expect(mayRunFreely({ ...platform, agent: "ask" }, true, "reviewed")).toBe(false);
  // Trusting the agent needs no standing consent: the agent decides.
  expect(mayRunFreely(capability, false, "trust_agent")).toBe(true);
  expect(mayRunFreely({ ...capability, agent: "ask" }, true, "trust_agent")).toBe(false);
});
