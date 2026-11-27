import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "./api-client";
import {
  endConversationEnvironment,
  readConversationEnvironments,
  startConversationEnvironment,
} from "./conversation-environments-api";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const agentId = "11111111-1111-4111-8111-111111111111";
const otherAgent = "22222222-2222-4222-8222-222222222222";
const ready = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: agentId,
  kind: "browser",
  execution_target: "agent",
  state: "ready",
  control: "human",
  can_control: true,
  expires_at: "2026-11-27T14:00:00+00:00",
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};

beforeEach(() => vi.resetAllMocks());

describe("conversation environments", () => {
  it("reads both kinds without provisioning or starting a model", async () => {
    const data = { items: [ready, { ...ready, kind: "desktop" }] };
    vi.mocked(apiClient.get).mockResolvedValue(data);
    expect(await readConversationEnvironments("chat/one", agentId)).toEqual(data);
    expect(apiClient.get).toHaveBeenCalledWith(
      `/conversations/chat%2Fone/environments?agent_id=${agentId}&project_execution_target=agent`,
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("opens only the named kind and lets the backend resolve its provider", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ ...ready, provider_handle: "not-public" });
    expect(await startConversationEnvironment("chat", agentId, "browser")).toEqual(ready);
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/chat/environments/browser", {
      agent_id: agentId,
      project_execution_target: "agent",
    });
  });

  it("ends only through the explicit end operation", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    await endConversationEnvironment("chat/one", agentId, "desktop");
    expect(apiClient.delete).toHaveBeenCalledWith(
      `/conversations/chat%2Fone/environments/desktop?agent_id=${agentId}&project_execution_target=agent`,
    );
  });

  it.each([
    { items: [ready] },
    { items: [ready, ready] },
    { items: [ready, { ...ready, kind: "desktop", agent_id: otherAgent }] },
    { items: [ready, { ...ready, kind: "desktop", state: "invented" }] },
  ])("refuses incomplete, duplicate or mismatched readiness", async (data) => {
    vi.mocked(apiClient.get).mockResolvedValue(data);
    await expect(readConversationEnvironments("chat", agentId)).rejects.toThrow();
  });

  it.each([
    { ...ready, agent_id: otherAgent },
    { ...ready, kind: "desktop" },
    { ...ready, can_control: "yes" },
  ])(
    "refuses a start response for a different environment or malformed authority",
    async (data) => {
      vi.mocked(apiClient.post).mockResolvedValue(data);
      await expect(startConversationEnvironment("chat", agentId, "browser")).rejects.toThrow();
    },
  );

  it("preserves a controlled provisioning refusal instead of displaying an empty ready view", async () => {
    const refused = {
      ...ready,
      id: null,
      state: "not_started",
      control: "none",
      can_control: false,
      expires_at: null,
      refusal: { code: "capacity_reached", message: "Environment capacity reached" },
    };
    vi.mocked(apiClient.post).mockResolvedValue(refused);
    expect(await startConversationEnvironment("chat", agentId, "browser")).toEqual(refused);
  });

  it("propagates a denied operation", async () => {
    const denied = new Error("forbidden");
    vi.mocked(apiClient.delete).mockRejectedValue(denied);
    await expect(endConversationEnvironment("chat", agentId, "desktop")).rejects.toBe(denied);
  });
});
