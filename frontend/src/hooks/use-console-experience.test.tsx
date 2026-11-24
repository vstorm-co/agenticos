import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import { useConsoleExperience } from "./use-console-experience";
import { useAuthStore, useOrgStore } from "@/stores";
import { DEFAULT_CHAT_HOME, type ConsoleExperience } from "@/lib/console-experience-api";
import { qk } from "@/lib/query-keys";
const api = vi.hoisted(() => ({
  read: vi.fn(),
  save: vi.fn(),
  error: vi.fn(),
  fallback: null as string | null,
}));
vi.mock("@/lib/console-experience-api", async (original) => ({
  ...(await original<typeof import("@/lib/console-experience-api")>()),
  readConsoleExperience: api.read,
  saveConsoleExperience: api.save,
}));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => useOrgStore((state) => state.activeOrgId) ?? api.fallback,
}));
vi.mock("sonner", () => ({ toast: { error: api.error } }));
let client: QueryClient;
const state = (overrides: Partial<ConsoleExperience> = {}): ConsoleExperience => ({
  reminders: {
    availability: true,
    organization_defaults: {},
    preferences: {},
    effective: { enabled: true, snooze_days: 1 },
  },
  availability: DEFAULT_CHAT_HOME,
  organization_defaults: {},
  preferences: {},
  effective: DEFAULT_CHAT_HOME,
  ...overrides,
});
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
beforeEach(() => {
  vi.clearAllMocks();
  api.fallback = null;
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({
    user: { id: "user-one", email: "one@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org-one" });
  api.read.mockResolvedValue(state());
  api.save.mockResolvedValue(
    state({ preferences: { inbox: false }, effective: { ...DEFAULT_CHAT_HOME, inbox: false } }),
  );
});
it("adopts server effective values and saves a deliberate personal choice", async () => {
  api.read.mockResolvedValue(state({ effective: { ...DEFAULT_CHAT_HOME, greeting: false } }));
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.effective.greeting).toBe(false));
  act(() => result.current.save.mutate({ preferences: { inbox: false } }));
  await waitFor(() => expect(result.current.effective.inbox).toBe(false));
  expect(api.save).toHaveBeenCalledWith("org-one", { preferences: { inbox: false } });
  act(() => result.current.save.mutate({ preferences: null }));
  await waitFor(() => expect(api.save).toHaveBeenLastCalledWith("org-one", { preferences: null }));
});
it("does not fetch or save without an account and active membership", async () => {
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
  const { result } = renderHook(useConsoleExperience, { wrapper });
  expect(api.read).not.toHaveBeenCalled();
  act(() => result.current.save.mutate({ preferences: { greeting: false } }));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(api.save).not.toHaveBeenCalled();
});
it("never applies a late response from one workspace to another", async () => {
  let resolveFirst: (value: ConsoleExperience) => void = () => {
    throw new Error("No request");
  };
  api.read.mockImplementation((org: string) =>
    org === "org-one"
      ? new Promise<ConsoleExperience>((resolve) => {
          resolveFirst = resolve;
        })
      : Promise.resolve(
          state({
            preferences: { starters: false },
            effective: { ...DEFAULT_CHAT_HOME, starters: false },
          }),
        ),
  );
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(api.read).toHaveBeenCalledWith("org-one"));
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  await waitFor(() => expect(result.current.effective.starters).toBe(false));
  await act(async () => resolveFirst(state({ effective: { ...DEFAULT_CHAT_HOME, inbox: false } })));
  expect(result.current.effective.inbox).toBe(true);
  expect(client.getQueryData(qk.consoleExperience.member("org-one", "user-one"))).toBeDefined();
});
it("refuses a queued edit after workspace or account ownership changes", async () => {
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  const previous = result.current.save;
  act(() => {
    useOrgStore.setState({ activeOrgId: "org-two" });
    previous.mutate({ preferences: { greeting: false } });
  });
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(api.save).not.toHaveBeenCalled();
});
it("reports a failed save without replacing the last effective server value", async () => {
  api.save.mockRejectedValue(new Error("offline"));
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  act(() => result.current.save.mutate({ preferences: { inbox: false } }));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(result.current.effective.inbox).toBe(true);
});

it("keeps a completed old-workspace save in its captured cache after switching", async () => {
  let finish: (value: ConsoleExperience) => void = () => {
    throw new Error("No save");
  };
  api.save.mockImplementationOnce(
    () =>
      new Promise<ConsoleExperience>((resolve) => {
        finish = resolve;
      }),
  );
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  act(() => result.current.save.mutate({ preferences: { inbox: false } }));
  await waitFor(() =>
    expect(api.save).toHaveBeenCalledWith("org-one", { preferences: { inbox: false } }),
  );
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  await waitFor(() => expect(api.read).toHaveBeenCalledWith("org-two"));
  await act(async () => finish(state({ effective: { ...DEFAULT_CHAT_HOME, inbox: false } })));
  await waitFor(() =>
    expect(
      client.getQueryData<ConsoleExperience>(qk.consoleExperience.member("org-one", "user-one"))
        ?.effective.inbox,
    ).toBe(false),
  );
  expect(result.current.effective.inbox).toBe(true);
});

it("awaits a reminder edit and uses the captured default tenant before explicit selection", async () => {
  api.fallback = "org-one";
  useOrgStore.setState({ activeOrgId: null });
  const reply = state({
    reminders: {
      availability: true,
      organization_defaults: {},
      preferences: { enabled: false, snooze_days: 7 },
      effective: { enabled: false, snooze_days: 7 },
    },
  });
  api.save.mockResolvedValue(reply);
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  await act(async () => {
    expect(
      await result.current.save.mutateAsync({ reminders: { enabled: false, snooze_days: 7 } }),
    ).toEqual(reply);
  });
  expect(api.save).toHaveBeenCalledWith("org-one", {
    reminders: { enabled: false, snooze_days: 7 },
  });
});
it("refuses manual refresh without a membership and a previous account's queued edit", async () => {
  const { result } = renderHook(useConsoleExperience, { wrapper });
  await waitFor(() => expect(result.current.data).toBeDefined());
  const old = result.current.save;
  act(() =>
    useAuthStore.setState({
      user: { id: "user-two", email: "two@example.com", is_active: true, created_at: "2026-01-01" },
    }),
  );
  act(() => old.mutate({ preferences: { inbox: false } }));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(api.save).not.toHaveBeenCalled();
  act(() => {
    useAuthStore.setState({ user: null });
    useOrgStore.setState({ activeOrgId: null });
  });
  api.read.mockClear();
  await act(async () => {
    await result.current.refetch();
  });
  expect(api.read).not.toHaveBeenCalled();
});
