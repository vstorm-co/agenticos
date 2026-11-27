import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useAuthStore, useOrgStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import {
  readDeploymentOnboarding,
  saveDeploymentOnboarding,
  readOnboarding,
  saveOnboardingScope,
  type Onboarding,
  type DeploymentOnboarding,
} from "@/lib/onboarding-api";
import { useDeploymentStart } from "./use-deployment-start";
import { useStart } from "./use-start";
vi.mock("@/lib/onboarding-api", async (original) => ({
  ...(await original<typeof import("@/lib/onboarding-api")>()),
  readDeploymentOnboarding: vi.fn(),
  saveDeploymentOnboarding: vi.fn(),
  readOnboarding: vi.fn(),
  saveOnboardingScope: vi.fn(),
}));
const user = {
  id: "user",
  email: "user@example.com",
  is_active: true,
  is_app_admin: true,
  created_at: "2026-01-01T00:00:00Z",
};
const sample: Onboarding = {
  organization_id: "org",
  organization_name: "Acme",
  goal: null,
  dismissed: false,
  completed: true,
  snoozed_until: null,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  agents: [],
  setup_agent: null,
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: true,
  has_activity: true,
};
const deployment: DeploymentOnboarding = {
  ...sample,
  organization_id: null,
  organization_name: null,
  active_scope: "deployment",
  scopes: [
    {
      scope: "deployment",
      applicable: true,
      completed: false,
      completed_at: null,
      current_step: null,
      updated_at: null,
    },
    {
      scope: "organization",
      applicable: false,
      completed: false,
      completed_at: null,
      current_step: null,
      updated_at: null,
    },
    {
      scope: "personal",
      applicable: false,
      completed: false,
      completed_at: null,
      current_step: null,
      updated_at: null,
    },
  ],
};
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user });
  useOrgStore.setState({ activeOrgId: null });
  vi.mocked(readDeploymentOnboarding).mockResolvedValue(deployment);
  vi.mocked(readOnboarding).mockResolvedValue(sample);
});
it.each(["member", "organization", "logged out", "disabled"])(
  "does not fetch deployment setup for %s",
  (reason) => {
    if (reason === "member") useAuthStore.setState({ user: { ...user, is_app_admin: false } });
    if (reason === "organization") useOrgStore.setState({ activeOrgId: "org" });
    if (reason === "logged out") useAuthStore.setState({ user: null });
    const { wrapper } = setup();
    const { result } = renderHook(() => useDeploymentStart(reason !== "disabled"), { wrapper });
    expect(result.current.allowed).toBe(false);
    expect(readDeploymentOnboarding).not.toHaveBeenCalled();
  },
);
it("supports first deployment without reading an organization or changing personal completion", async () => {
  vi.mocked(saveDeploymentOnboarding).mockResolvedValue({ ...deployment, active_scope: null });
  const { wrapper, client } = setup();
  const { result } = renderHook(() => useDeploymentStart(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(readOnboarding).not.toHaveBeenCalled();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  await act(async () => {
    await result.current.save.mutateAsync({ completed: true });
  });
  expect(saveDeploymentOnboarding).toHaveBeenCalledWith({ completed: true });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.onboarding.all() });
  expect(result.current.data?.completed).toBe(true);
});
it("refuses a stale deployment save after organization selection", async () => {
  const { wrapper } = setup();
  const { result } = renderHook(() => useDeploymentStart(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  const save = result.current.save;
  act(() => useOrgStore.setState({ activeOrgId: "org" }));
  await expect(save.mutateAsync({ completed: true })).rejects.toThrow();
  expect(saveDeploymentOnboarding).not.toHaveBeenCalled();
});
it("never repopulates a signed-out account from a delayed deployment completion", async () => {
  const delayed = Promise.withResolvers<DeploymentOnboarding>();
  vi.mocked(saveDeploymentOnboarding).mockReturnValue(delayed.promise);
  const { wrapper, client } = setup();
  const { result } = renderHook(() => useDeploymentStart(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  const pending = result.current.save.mutateAsync({ completed: true });
  await waitFor(() => expect(saveDeploymentOnboarding).toHaveBeenCalledTimes(1));
  act(() => {
    useAuthStore.setState({ user: null });
    client.clear();
  });
  await act(async () => {
    delayed.resolve({ ...deployment, active_scope: null });
    await pending;
  });
  expect(client.getQueryData(qk.onboarding.deployment("user"))).toBeUndefined();
});
it("sends a shared completion only under the captured organization", async () => {
  useOrgStore.setState({ activeOrgId: "org" });
  vi.mocked(saveOnboardingScope).mockResolvedValue(sample);
  const { wrapper } = setup();
  const { result } = renderHook(() => useStart(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await result.current.saveScope.mutateAsync({
      scope: "organization",
      data: { completed: true },
    });
  });
  expect(saveOnboardingScope).toHaveBeenCalledWith("organization", { completed: true }, "org");
  const save = result.current.saveScope;
  act(() => useOrgStore.setState({ activeOrgId: "other" }));
  await expect(
    save.mutateAsync({ scope: "organization", data: { completed: true } }),
  ).rejects.toThrow();
  expect(saveOnboardingScope).toHaveBeenCalledTimes(1);
});
it("keeps a delayed old shared response out of the replacement actor's cache", async () => {
  useOrgStore.setState({ activeOrgId: "org" });
  const delayed = Promise.withResolvers<Onboarding>();
  vi.mocked(saveOnboardingScope).mockReturnValue(delayed.promise);
  const { wrapper, client } = setup();
  const { result } = renderHook(() => useStart(), { wrapper });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  const pending = result.current.saveScope.mutateAsync({
    scope: "organization",
    data: { completed: true },
  });
  await waitFor(() => expect(saveOnboardingScope).toHaveBeenCalledTimes(1));
  act(() => {
    useAuthStore.setState({ user: null });
    client.clear();
  });
  await act(async () => {
    delayed.resolve(sample);
    await pending;
  });
  expect(client.getQueryData(qk.onboarding.state("user", "org"))).toBeUndefined();
});
