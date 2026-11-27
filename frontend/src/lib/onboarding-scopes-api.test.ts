import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import {
  readOnboarding,
  readDeploymentOnboarding,
  saveDeploymentOnboarding,
  saveOnboardingScope,
  shouldOfferStart,
  type StartScope,
  type StartScopeState,
} from "./onboarding-api";
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), patch: vi.fn() } }));
const id = "00000000-0000-4000-8000-000000000001";
const scopes: StartScopeState[] = (["deployment", "organization", "personal"] as const).map(
  (scope) => ({
    scope,
    applicable: true,
    completed: false,
    completed_at: null,
    current_step: null,
    updated_at: null,
  }),
);
const sample = {
  organization_id: id,
  organization_name: "Acme",
  goal: null,
  dismissed: true,
  completed: true,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  agents: [],
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: true,
  scopes,
  active_scope: "deployment",
};
beforeEach(() => vi.clearAllMocks());
it("reads shared setup for completed users and writes only the explicit scope", async () => {
  vi.mocked(apiClient.get).mockResolvedValue(sample);
  const data = await readOnboarding();
  expect(shouldOfferStart(data)).toBe(true);
  vi.mocked(apiClient.patch).mockResolvedValue(sample);
  expect((await saveOnboardingScope("deployment", { completed: true }, id)).completed).toBe(true);
  expect(apiClient.patch).toHaveBeenCalledWith(
    "/me/onboarding/scopes/deployment",
    { completed: true },
    { headers: { "X-Organization-Id": id } },
  );
});
it("uses a dedicated no-organization endpoint without a fabricated identifier", async () => {
  const deployment = {
    ...sample,
    organization_id: null,
    organization_name: null,
    scopes: scopes.map((scope) => ({ ...scope, applicable: scope.scope === "deployment" })),
  };
  vi.mocked(apiClient.get).mockResolvedValue(deployment);
  expect((await readDeploymentOnboarding()).organization_id).toBeNull();
  expect(apiClient.get).toHaveBeenCalledWith("/me/onboarding/deployment");
  vi.mocked(apiClient.patch).mockResolvedValue(deployment);
  await saveDeploymentOnboarding({ current_step: "admin.deployment" });
  expect(apiClient.patch).toHaveBeenCalledWith("/me/onboarding/deployment", {
    current_step: "admin.deployment",
  });
  vi.mocked(apiClient.get).mockResolvedValue(sample);
  await expect(readDeploymentOnboarding()).rejects.toThrow();
});
it.each([
  { scopes: scopes.slice(1) },
  { scopes: [...scopes].reverse() },
  { scopes: undefined },
  { active_scope: undefined },
  { active_scope: null },
  { active_scope: "personal" as StartScope },
  { scopes: scopes.map((scope) => ({ ...scope, applicable: false })) },
  { scopes: scopes.map((scope) => ({ ...scope, completed: true })) },
])("refuses malformed or order-bypassing scope envelopes: %j", async (override) => {
  vi.mocked(apiClient.get).mockResolvedValue({ ...sample, ...override });
  await expect(readOnboarding()).rejects.toThrow();
});
it("permits a snoozed personal stage and skips unavailable shared authority", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({
    ...sample,
    active_scope: null,
    scopes: scopes.map((scope) => ({ ...scope, applicable: scope.scope === "personal" })),
  });
  expect((await readOnboarding()).active_scope).toBeNull();
  vi.mocked(apiClient.get).mockResolvedValue({
    ...sample,
    active_scope: "organization",
    scopes: scopes.map((scope) => ({ ...scope, applicable: scope.scope !== "deployment" })),
  });
  expect((await readOnboarding()).active_scope).toBe("organization");
});
