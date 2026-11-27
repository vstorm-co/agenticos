import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type { ConversationEnvironment } from "@/lib/conversation-environments-api";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useConversationEnvironments } from "./use-conversation-environments";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const agent = "11111111-1111-4111-8111-111111111111";
const browser: ConversationEnvironment = {
  id: "33333333-3333-4333-8333-333333333333",
  agent_id: agent,
  kind: "browser",
  execution_target: "agent",
  state: "ready",
  control: "none",
  can_control: true,
  expires_at: null,
  refusal: null,
  session_lifetime: "conversation",
  idle_seconds: 900,
};
const desktop: ConversationEnvironment = { ...browser, kind: "desktop", state: "not_started" };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({
    sessionOwnerId: "owner",
    user: { id: "actor", email: "reader@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org-one" });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [browser, desktop] });
});

it("reads availability passively and keeps both kinds", async () => {
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items).toEqual([browser, desktop]));
  expect(apiClient.post).not.toHaveBeenCalled();
  expect(apiClient.delete).not.toHaveBeenCalled();
  expect(result.current.error).toBeNull();
});

it.each([
  [null, agent, true],
  ["chat", null, true],
  ["chat", agent, false],
] as const)("does not read an absent or hidden environment", (conversation, selected, enabled) => {
  const { result } = renderHook(
    () => useConversationEnvironments(conversation, selected, enabled),
    { wrapper },
  );
  expect(apiClient.get).not.toHaveBeenCalled();
  expect(result.current.items).toBeUndefined();
});

it("does not confuse a denied read with no environment", async () => {
  const denied = new Error("denied");
  vi.mocked(apiClient.get).mockRejectedValue(denied);
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.error).toBe(denied));
  expect(result.current.items).toBeUndefined();
});

it("refreshes a started environment and ends only on the explicit command", async () => {
  vi.mocked(apiClient.post).mockResolvedValue(browser);
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items).toBeDefined());
  await act(async () => {
    expect(await result.current.start({ conversation: "chat", agent, kind: "browser" })).toEqual(
      browser,
    );
  });
  expect(apiClient.get).toHaveBeenCalledTimes(2);
  expect(apiClient.delete).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.end({ conversation: "chat", agent, kind: "browser" });
  });
  expect(apiClient.delete).toHaveBeenCalledOnce();
  expect(apiClient.get).toHaveBeenCalledTimes(3);
});

it("updates only the kind named by a validated live state", async () => {
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items).toBeDefined());
  await act(async () => {
    await result.current.remember({ ...browser, control: "agent" });
  });
  await waitFor(() => expect(result.current.items?.[0]?.control).toBe("agent"));
  expect(result.current.items?.[1]).toEqual(desktop);
  await act(async () => {
    await result.current.refresh();
  });
  await waitFor(() => expect(result.current.items?.[0]?.control).toBe("none"));
});

it("holds an old organization's frames outside the newly selected tenant", async () => {
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items).toBeDefined());
  const oldRemember = result.current.remember;
  vi.mocked(apiClient.get).mockResolvedValue({
    items: [{ ...browser, state: "expired" }, desktop],
  });
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  await waitFor(() => expect(result.current.items?.[0]?.state).toBe("expired"));
  await act(async () => {
    await oldRemember({ ...browser, control: "human" });
  });
  expect(result.current.items?.[0]?.state).toBe("expired");
  expect(result.current.items?.[0]?.control).toBe("none");
});

it.each(["personal", "signed-out"])("scopes passive reads for a %s session", async (kind) => {
  useAuthStore.setState({ sessionOwnerId: null });
  if (kind === "signed-out") useAuthStore.setState({ user: null });
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  if (kind === "personal") await waitFor(() => expect(result.current.items).toBeDefined());
  else expect(apiClient.get).not.toHaveBeenCalled();
});

it("does not install a live frame before a listing exists", async () => {
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, false), {
    wrapper,
  });
  await act(async () => {
    await result.current.remember(browser);
  });
  expect(result.current.items).toBeUndefined();
});

it("polls only while preparation is still starting", async () => {
  vi.mocked(apiClient.get)
    .mockResolvedValueOnce({ items: [{ ...browser, state: "starting" }, desktop] })
    .mockResolvedValue({ items: [browser, desktop] });
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items?.[0]?.state).toBe("starting"));
  await waitFor(() => expect(result.current.items?.[0]?.state).toBe("ready"));
  expect(apiClient.get).toHaveBeenCalledTimes(2);
});

it("limits pending Start and End indicators to the operation's identity", async () => {
  let started!: (value: ConversationEnvironment) => void;
  let ended!: () => void;
  vi.mocked(apiClient.post).mockImplementation(
    () =>
      new Promise((resolve) => {
        started = resolve;
      }),
  );
  vi.mocked(apiClient.delete).mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        ended = resolve;
      }),
  );
  const { result } = renderHook(() => useConversationEnvironments("chat", agent, true), {
    wrapper,
  });
  await waitFor(() => expect(result.current.items).toBeDefined());
  let opening!: Promise<ConversationEnvironment>;
  act(() => {
    opening = result.current.start({ conversation: "chat", agent, kind: "browser" });
  });
  await waitFor(() => expect(result.current.isStarting).toBe(true));
  await act(async () => {
    started(browser);
    await opening;
  });
  let closing!: Promise<void>;
  act(() => {
    closing = result.current.end({ conversation: "chat", agent, kind: "browser" });
  });
  await waitFor(() => expect(result.current.isEnding).toBe(true));
  act(() => useOrgStore.setState({ activeOrgId: "another-org" }));
  expect(result.current.isEnding).toBe(false);
  await act(async () => {
    ended();
    await closing;
  });
});
