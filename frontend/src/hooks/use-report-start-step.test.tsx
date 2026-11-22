import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useAuthStore, useOrgStore } from "@/stores";
import { apiClient } from "@/lib/api-client";
import type { StartStep } from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";
import { useReportStartStep } from "./use-report-start-step";
const notices = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/lib/api-client", () => ({ apiClient: { patch: vi.fn() } }));
vi.mock("sonner", () => ({ toast: notices }));
const org = "00000000-0000-0000-0000-000000000001";
const result = {
  organization_id: org,
  organization_name: "One",
  goal: null,
  dismissed: false,
  completed: false,
  can_prepare: false,
  can_configure_model: false,
  support_email: null,
  agents: [],
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: false,
};
function makeWrapper(
  client = new QueryClient({ defaultOptions: { mutations: { retry: false } } }),
) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({
    user: { id: "person", email: "one@example.com", is_active: true, created_at: "2026-11-22" },
  });
  useOrgStore.setState({ activeOrgId: org });
  vi.mocked(apiClient.patch).mockResolvedValue(result);
});
it("reports actual forward and backward steps to the explicit membership", async () => {
  const { rerender } = renderHook(
    ({ step }: { step: StartStep }) => useReportStartStep(step, org),
    { wrapper: makeWrapper(), initialProps: { step: "member.profile" as StartStep } },
  );
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/me/onboarding",
      { current_step: "member.profile" },
      { headers: { "X-Organization-Id": org } },
    ),
  );
  rerender({ step: "member.context" });
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  rerender({ step: "member.profile" });
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(3));
});
it("does not report a different workspace or disabled journey", () => {
  renderHook(() => useReportStartStep("member.profile", "another"), { wrapper: makeWrapper() });
  renderHook(() => useReportStartStep("member.profile", org, false), { wrapper: makeWrapper() });
  expect(apiClient.patch).not.toHaveBeenCalled();
});
it("offers retry on a refused progress write", async () => {
  vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("refused"));
  renderHook(() => useReportStartStep("member.profile", org), { wrapper: makeWrapper() });
  await waitFor(() => expect(notices.error).toHaveBeenCalled());
  const options = notices.error.mock.calls[0]?.[1] as { action: { onClick: () => void } };
  act(() => options.action.onClick());
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
});

it("serializes rapid step reports instead of allowing late responses to reorder them", async () => {
  let release: (() => void) | undefined;
  vi.mocked(apiClient.patch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = () => resolve(result);
      }),
  );
  const { rerender } = renderHook(
    ({ step }: { step: StartStep }) => useReportStartStep(step, org),
    { wrapper: makeWrapper(), initialProps: { step: "member.profile" as StartStep } },
  );
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
  rerender({ step: "member.context" });
  expect(apiClient.patch).toHaveBeenCalledTimes(1);
  await act(async () => release?.());
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  expect(vi.mocked(apiClient.patch).mock.calls[1]?.[1]).toEqual({ current_step: "member.context" });
});

it("does not replace completion with an older progress response", async () => {
  const client = new QueryClient();
  let release: (() => void) | undefined;
  vi.mocked(apiClient.patch).mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        release = () => resolve(result);
      }),
  );
  renderHook(() => useReportStartStep("member.profile", org), { wrapper: makeWrapper(client) });
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
  client.setQueryData(qk.onboarding.state("person", org), { ...result, completed: true });
  await act(async () => release?.());
  expect(client.getQueryData(qk.onboarding.state("person", org))).toMatchObject({
    completed: true,
  });
});
it.each(["organization", "account", "logout"])(
  "discards a queued report after the active %s changes without a stale error notice",
  async (scope) => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const pending = Promise.withResolvers<typeof result>();
    vi.mocked(apiClient.patch).mockReturnValueOnce(pending.promise);
    const { rerender } = renderHook(
      ({ step, enabled }: { step: StartStep; enabled: boolean }) =>
        useReportStartStep(step, org, enabled),
      {
        wrapper: makeWrapper(client),
        initialProps: { step: "member.profile" as StartStep, enabled: true },
      },
    );
    await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(1));
    rerender({ step: "member.context", enabled: true });
    act(() => {
      rerender({ step: "member.context", enabled: false });
      if (scope === "organization") useOrgStore.setState({ activeOrgId: "another" });
      else if (scope === "logout") useAuthStore.setState({ user: null });
      else
        useAuthStore.setState({
          user: {
            id: "another-person",
            email: "two@example.com",
            is_active: true,
            created_at: "2026-11-22",
          },
        });
    });
    await act(async () => pending.resolve(result));
    await waitFor(() => expect(client.isMutating()).toBe(0));
    expect(apiClient.patch).toHaveBeenCalledTimes(1);
    expect(notices.error).not.toHaveBeenCalled();
  },
);
it("does not retry a historical step after moving to a newer step", async () => {
  vi.mocked(apiClient.patch).mockRejectedValueOnce(new Error("refused"));
  const { rerender } = renderHook(
    ({ step }: { step: StartStep }) => useReportStartStep(step, org),
    { wrapper: makeWrapper(), initialProps: { step: "member.profile" as StartStep } },
  );
  await waitFor(() => expect(notices.error).toHaveBeenCalled());
  const options = notices.error.mock.calls[0]?.[1] as { action: { onClick: () => void } };
  rerender({ step: "member.tools" });
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  act(() => options.action.onClick());
  expect(apiClient.patch).toHaveBeenCalledTimes(2);
});
