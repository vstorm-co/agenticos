import { expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import {
  listPersonalModelKeys,
  agentModelConnection,
  savePersonalModelKey,
  deletePersonalModelKey,
  startCopilotSignIn,
  pollCopilotSignIn,
} from "./personal-model-keys-api";
vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
it("sends credentials only in the mutation body and uses metadata-only reads", () => {
  listPersonalModelKeys();
  agentModelConnection("agent");
  const expected_destination = {
    profile_id: "profile",
    provider: "openai",
    endpoint: null,
    model: "fixed",
  };
  savePersonalModelKey({ agentId: "agent", api_key: "private", expected_destination });
  deletePersonalModelKey("mine");
  expect(apiClient.get).toHaveBeenCalledWith("/personal-model-keys");
  expect(apiClient.get).toHaveBeenCalledWith("/personal-model-keys/agents/agent");
  expect(apiClient.put).toHaveBeenCalledWith("/personal-model-keys/agents/agent", {
    api_key: "private",
    expected_destination,
  });
  expect(apiClient.delete).toHaveBeenCalledWith("/personal-model-keys/mine");
});

it("sends Copilot sign-in intent and poll handles only in mutation bodies", () => {
  const destination = {
    profile_id: "profile",
    provider: "github_copilot",
    endpoint: null,
    model: "plan-model",
  };
  startCopilotSignIn("agent", destination);
  pollCopilotSignIn("agent", "private-handle");
  expect(apiClient.post).toHaveBeenCalledWith("/personal-model-keys/agents/agent/copilot/sign-in", {
    expected_destination: destination,
  });
  expect(apiClient.post).toHaveBeenCalledWith("/personal-model-keys/agents/agent/copilot/poll", {
    handle: "private-handle",
  });
});
