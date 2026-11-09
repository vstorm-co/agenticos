import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "./api-client";
import {
  previewMemberStart,
  exampleChat,
  prepareStarter,
  readOnboarding,
  shouldOfferStart,
  saveOnboarding,
  startGoal,
} from "./onboarding-api";
vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn() } }));
const id = "00000000-0000-4000-8000-000000000001";
const state = {
  organization_id: id,
  organization_name: "Demo",
  goal: null,
  dismissed: false,
  setup_agent: null,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  agents: [],
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: false,
};
beforeEach(() => vi.clearAllMocks());
it("validates reads and never accepts a malformed readiness response", async () => {
  vi.mocked(apiClient.get).mockResolvedValue(state);
  expect(await readOnboarding()).toEqual({
    ...state,
    has_activity: false,
    completed: false,
    snoozed_until: null,
  });
  vi.mocked(apiClient.get).mockResolvedValue({ has_result: true });
  await expect(readOnboarding()).rejects.toThrow();
});
it("saves preferences and validates the returned state", async () => {
  vi.mocked(apiClient.patch).mockResolvedValue({ ...state, goal: "meeting" });
  expect((await saveOnboarding({ goal: "meeting" })).goal).toBe("meeting");
  expect(apiClient.patch).toHaveBeenCalledWith("/me/onboarding", { goal: "meeting" });
});
it("prepares only the explicitly selected model", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ id, name: "Starter" });
  expect(await prepareStarter(id)).toEqual({ id, name: "Starter" });
  expect(apiClient.post).toHaveBeenCalledWith("/me/onboarding/starter", { model_profile_id: id });
});
it("keeps only an example identity in the chat link and rejects unknown examples", () => {
  const link = new URL(exampleChat(id, "meeting"), "https://example.com");
  expect(link.searchParams.get("with")).toBe(id);
  expect(link.searchParams.get("example")).toBe("meeting");
  expect(link.searchParams.get("new")).toBeTruthy();
  expect(startGoal("document")).toBe("document");
  expect(startGoal("<script>")).toBeNull();
  expect(startGoal(null)).toBeNull();
});

it("validates a read-only teammate preview", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ has_common_agent: false });
  expect(await previewMemberStart(id)).toEqual({ has_common_agent: false });
  expect(apiClient.get).toHaveBeenCalledWith(`/me/onboarding/members/${id}`);
});

it.each(["activity", "agent", "dismissed", "completed", "walkthrough"])(
  "does not offer repeated onboarding for %s",
  (reason) => {
    const data = {
      dismissed: false,
      completed: false,
      has_result: false,
      has_activity: false,
      agents: new Array<{ id: string; name: string }>(),
    };
    expect(shouldOfferStart(data)).toBe(true);
    if (reason === "activity") data.has_activity = true;
    if (reason === "agent") data.agents = [{ id, name: "Existing agent" }];
    if (reason === "dismissed") data.dismissed = true;
    if (reason === "completed") data.has_result = true;
    if (reason === "walkthrough") data.completed = true;
    expect(shouldOfferStart(data)).toBe(false);
  },
);

it("accepts a setup-only starter without adding it to runnable agents", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ ...state, setup_agent: { id, name: "AgenticOS" } });
  const result = await readOnboarding();
  expect(result.setup_agent).toEqual({ id, name: "AgenticOS" });
  expect(result.agents).toEqual([]);
  expect(result.can_prepare).toBe(false);
});
it("keeps older readiness responses compatible when they omit the setup candidate", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ ...state, setup_agent: undefined });
  expect((await readOnboarding()).setup_agent).toBeNull();
});
