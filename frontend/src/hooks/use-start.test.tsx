import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { useStart, useMemberStartPreview } from "./use-start";
import {
  readOnboarding,
  saveOnboarding,
  prepareStarter,
  previewMemberStart,
} from "@/lib/onboarding-api";
import type { Onboarding } from "@/lib/onboarding-api";
import { qk } from "@/lib/query-keys";
const sample: Onboarding = {
  organization_id: "org",
  organization_name: "Demo",
  goal: null,
  dismissed: false,
  completed: false,
  snoozed_until: null,
  setup_agent: null,
  can_prepare: true,
  can_configure_model: true,
  support_email: null,
  agents: [],
  latest_conversation_id: null,
  latest_completed_at: null,
  has_result: false,
  has_activity: false,
};
const scope = vi.hoisted(() => ({ user: "user" as string | null, org: "org" as string | null }));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (state: { user: { id: string } | null }) => unknown) =>
    pick({ user: scope.user ? { id: scope.user } : null }),
  useOrgStore: (pick: (state: { activeOrgId: string | null }) => unknown) =>
    pick({ activeOrgId: scope.org }),
}));
vi.mock("@/lib/onboarding-api", () => ({
  readOnboarding: vi.fn(),
  saveOnboarding: vi.fn(),
  prepareStarter: vi.fn(),
  previewMemberStart: vi.fn(),
}));
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(() => useStart(), { wrapper }) };
}
beforeEach(() => {
  vi.clearAllMocks();
  scope.user = "user";
  scope.org = "org";
});
it("does not fetch personal state without both identity and organization", () => {
  scope.user = null;
  scope.org = null;
  const { result } = mount();
  expect(result.current.waitingForScope).toBe(true);
  expect(readOnboarding).not.toHaveBeenCalled();
});
it("reads state under both identities and updates only that scoped cache", async () => {
  vi.mocked(readOnboarding).mockResolvedValue(sample);
  const saved: Onboarding = { ...sample, goal: "meeting" };
  vi.mocked(saveOnboarding).mockResolvedValue(saved);
  const { result, client, rerender } = mount();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await result.current.save.mutateAsync({ goal: "meeting" });
  });
  expect(client.getQueryData(qk.onboarding.state("user", "org"))).toEqual(saved);
  expect(client.getQueryData(qk.onboarding.state("user", "other"))).toBeUndefined();
  scope.org = "other";
  rerender();
  await waitFor(() => expect(readOnboarding).toHaveBeenCalledTimes(2));
});
it("refreshes agents and readiness after explicit preparation", async () => {
  vi.mocked(readOnboarding).mockResolvedValue(sample);
  vi.mocked(prepareStarter).mockResolvedValue({ id: "agent", name: "Starter" });
  const { result, client } = mount();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  await act(async () => {
    await result.current.prepare.mutateAsync("model");
  });
  expect(prepareStarter).toHaveBeenCalledWith("model");
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.agents.all() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.onboarding.state("user", "org") });
});

it("isolates the read-only member preview across organization switches", async () => {
  vi.mocked(previewMemberStart).mockResolvedValue({ has_common_agent: false });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result, rerender } = renderHook(({ person }) => useMemberStartPreview(person), {
    wrapper,
    initialProps: { person: "" },
  });
  expect(previewMemberStart).not.toHaveBeenCalled();
  rerender({ person: "teammate" });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(client.getQueryData(qk.onboarding.preview("org", "teammate"))).toEqual({
    has_common_agent: false,
  });
  scope.org = "another";
  rerender({ person: "teammate" });
  await waitFor(() => expect(previewMemberStart).toHaveBeenCalledTimes(2));
});

it("does not request a teammate preview without an active organization", () => {
  scope.org = null;
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const { result } = renderHook(() => useMemberStartPreview("teammate"), { wrapper });
  expect(result.current.fetchStatus).toBe("idle");
  expect(previewMemberStart).not.toHaveBeenCalled();
});

it("keeps a delayed preference response in the initiating account and organization", async () => {
  vi.mocked(readOnboarding).mockResolvedValue(sample);
  let finish: ((state: Onboarding) => void) | undefined;
  vi.mocked(saveOnboarding).mockReturnValue(
    new Promise<Onboarding>((resolve) => {
      finish = resolve;
    }),
  );
  const { result, client, rerender } = mount();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  let pending: Promise<unknown> | undefined;
  act(() => {
    pending = result.current.save.mutateAsync({ goal: "meeting" });
  });
  await waitFor(() => expect(saveOnboarding).toHaveBeenCalledOnce());
  scope.user = "another-user";
  scope.org = "another-org";
  rerender();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.save.isPending).toBe(false);
  const saved: Onboarding = { ...sample, goal: "meeting" };
  await act(async () => {
    finish?.(saved);
    await pending;
  });
  expect(client.getQueryData(qk.onboarding.state("user", "org"))).toEqual(saved);
  expect(client.getQueryData(qk.onboarding.state("another-user", "another-org"))).toEqual(sample);
});
it("invalidates the initiating workspace after delayed assistant preparation", async () => {
  vi.mocked(readOnboarding).mockResolvedValue(sample);
  let finish: ((agent: { id: string; name: string }) => void) | undefined;
  vi.mocked(prepareStarter).mockReturnValue(
    new Promise((resolve) => {
      finish = resolve;
    }),
  );
  const { result, client, rerender } = mount();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  let pending: Promise<unknown> | undefined;
  act(() => {
    pending = result.current.prepare.mutateAsync("model");
  });
  await waitFor(() => expect(prepareStarter).toHaveBeenCalledOnce());
  scope.org = "another-org";
  rerender();
  expect(result.current.prepare.isPending).toBe(false);
  await act(async () => {
    finish?.({ id: "agent", name: "Starter" });
    await pending;
  });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.onboarding.state("user", "org") });
  expect(invalidate).not.toHaveBeenCalledWith({
    queryKey: qk.onboarding.state("user", "another-org"),
  });
});

it("refreshes an open start offer when its one-day snooze expires", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-08T12:00:00Z"));
  vi.mocked(readOnboarding)
    .mockResolvedValueOnce({ ...sample, dismissed: true, snoozed_until: "2026-11-09T12:00:00Z" })
    .mockResolvedValue(sample);
  const view = mount();
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(view.result.current.data?.dismissed).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(86_400_001);
    });
    expect(readOnboarding).toHaveBeenCalledTimes(2);
    expect(view.result.current.data?.dismissed).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(86_400_000);
    });
    expect(readOnboarding).toHaveBeenCalledTimes(2);
  } finally {
    view.unmount();
    view.client.clear();
    vi.useRealTimers();
  }
});

it("uses server time when the local clock is ahead of a snoozed offer", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-10T12:00:00Z"));
  vi.mocked(readOnboarding).mockResolvedValue({
    ...sample,
    dismissed: true,
    server_time: "2026-11-08T12:00:00Z",
    snoozed_until: "2026-11-09T12:00:00Z",
  });
  const view = mount();
  try {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_600_000);
    });
    expect(readOnboarding).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(82_800_001);
    });
    expect(readOnboarding).toHaveBeenCalledTimes(2);
  } finally {
    view.unmount();
    view.client.clear();
    vi.useRealTimers();
  }
});

it("does not restart a failed onboarding read when the dashboard mounts its checklist", async () => {
  vi.mocked(readOnboarding).mockRejectedValue(new Error("offline"));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const dashboard = renderHook(() => useStart(), { wrapper });
  await waitFor(() => expect(dashboard.result.current.isError).toBe(true));
  const checklist = renderHook(() => useStart(), { wrapper });
  expect(checklist.result.current.isLoading).toBe(false);
  expect(checklist.result.current.isError).toBe(true);
  expect(readOnboarding).toHaveBeenCalledTimes(1);
  await act(async () => {
    await checklist.result.current.refetch();
  });
  expect(readOnboarding).toHaveBeenCalledTimes(2);
});
