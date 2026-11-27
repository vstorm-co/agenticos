import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import type {
  ConversationEnvironment,
  ConversationEnvironmentList,
} from "@/lib/conversation-environments-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useConversationEnvironments } from "./use-conversation-environments";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));

const agent = "11111111-1111-4111-8111-111111111111";
const first: ConversationEnvironment = {
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
const desktop: ConversationEnvironment = {
  ...first,
  id: null,
  kind: "desktop",
  state: "not_started",
  can_control: false,
};
const key = qk.conversationEnvironments.context("owner", "actor", "org-one", "chat", agent);
const clients: QueryClient[] = [];

function listed(browser: ConversationEnvironment): ConversationEnvironmentList {
  return { items: [browser, desktop] };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setup(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return {
    client,
    ...renderHook(() => useConversationEnvironments("chat", agent, enabled), { wrapper }),
  };
}

beforeEach(() => {
  vi.resetAllMocks();
  useAuthStore.setState({
    sessionOwnerId: "owner",
    user: { id: "actor", email: "reader@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org-one" });
  vi.mocked(apiClient.get).mockResolvedValue(listed(first));
});
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
});

it("does not let a retained stream callback replace a newly created environment of the same kind", async () => {
  const { result, client } = setup();
  await waitFor(() => expect(result.current.items?.[0]).toEqual(first));
  const rememberFirst = result.current.remember;
  const replacement: ConversationEnvironment = {
    ...first,
    id: "44444444-4444-4444-8444-444444444444",
  };
  vi.mocked(apiClient.get).mockResolvedValue(listed(replacement));
  await act(async () => {
    await result.current.refresh();
  });
  await waitFor(() => expect(result.current.items?.[0]).toEqual(replacement));

  await act(async () => {
    await rememberFirst({ ...first, control: "human" });
  });

  expect(client.getQueryData<ConversationEnvironmentList>(key)?.items[0]).toEqual(replacement);
  await waitFor(() => expect(result.current.items).toEqual([replacement, desktop]));
});

it.each(["starting", "ready"] as const)(
  "does not let an earlier deferred %s GET overwrite a ready human-controlled live state",
  async (state) => {
    const earlier: ConversationEnvironment = { ...first, state, control: "none" };
    vi.mocked(apiClient.get).mockResolvedValueOnce(listed(earlier));
    const { result, client } = setup();
    await waitFor(() => expect(result.current.items?.[0]).toEqual(earlier));
    const response = deferred<ConversationEnvironmentList>();
    vi.mocked(apiClient.get).mockReturnValueOnce(response.promise);
    let refresh: ReturnType<typeof result.current.refresh> | undefined;
    act(() => {
      refresh = result.current.refresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));

    const live: ConversationEnvironment = { ...first, state: "ready", control: "human" };
    await act(async () => {
      await result.current.remember(live);
    });
    expect(client.getQueryData<ConversationEnvironmentList>(key)?.items[0]).toEqual(live);

    await act(async () => {
      response.resolve(listed(earlier));
      await response.promise;
      await refresh;
    });

    expect(client.getQueryData<ConversationEnvironmentList>(key)?.items).toEqual([live, desktop]);
    await waitFor(() => expect(result.current.items?.[0]).toEqual(live));
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.delete).not.toHaveBeenCalled();
  },
);

it("cancels an unfinished initial read before a fresh activity readiness request", async () => {
  const earlier = deferred<ConversationEnvironmentList>();
  const latest = deferred<ConversationEnvironmentList>();
  vi.mocked(apiClient.get).mockReturnValueOnce(earlier.promise).mockReturnValueOnce(latest.promise);
  const { result, client } = setup();
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledOnce());
  let refresh: ReturnType<typeof result.current.refresh> | undefined;
  act(() => {
    refresh = result.current.refresh();
  });
  await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(2));
  const owned = { ...first, control: "human" as const };
  await act(async () => {
    latest.resolve(listed(owned));
    await refresh;
  });
  expect(client.getQueryData<ConversationEnvironmentList>(key)?.items[0]).toEqual(owned);
  await act(async () => {
    earlier.resolve(listed({ ...first, id: null, state: "not_started" }));
    await earlier.promise;
  });
  await waitFor(() => expect(result.current.items?.[0]).toEqual(owned));
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("does not admit an obsolete actor's retained refresh callback", async () => {
  const { result, client } = setup(false);
  const previousRefresh = result.current.refresh;
  act(() =>
    useAuthStore.setState({
      user: {
        id: "other-actor",
        email: "other@example.com",
        is_active: true,
        created_at: "2026-01-01",
      },
    }),
  );
  await waitFor(() => expect(result.current.refresh).not.toBe(previousRefresh));
  expect(await previousRefresh()).toBeNull();
  expect(apiClient.get).not.toHaveBeenCalled();
  await act(async () => {
    await result.current.refresh();
  });
  expect(client.getQueryData(key)).toBeUndefined();
  const otherKey = qk.conversationEnvironments.context(
    "owner",
    "other-actor",
    "org-one",
    "chat",
    agent,
  );
  expect(client.getQueryData<ConversationEnvironmentList>(otherKey)?.items[0]).toEqual(first);
  expect(apiClient.get).toHaveBeenCalledOnce();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("rechecks authority after cancellation before starting a fresh request", async () => {
  const { result, client } = setup(false);
  const cancelled = deferred<void>();
  vi.spyOn(client, "cancelQueries").mockReturnValueOnce(cancelled.promise);
  let refresh: ReturnType<typeof result.current.refresh> | undefined;
  act(() => {
    refresh = result.current.refresh();
  });
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  await act(async () => {
    cancelled.resolve();
    expect(await refresh).toBeNull();
  });
  expect(apiClient.get).not.toHaveBeenCalled();
  expect(client.getQueryData(key)).toBeUndefined();
});

it("returns a read failure explicitly instead of claiming an empty successful environment list", async () => {
  const failure = new Error("Controlled readiness refusal");
  vi.mocked(apiClient.get).mockRejectedValue(failure);
  const { result } = setup(false);
  let response: Awaited<ReturnType<typeof result.current.refresh>> | undefined;
  await act(async () => {
    response = await result.current.refresh();
  });
  expect(response).toEqual({ data: undefined, error: failure });
  await waitFor(() => expect(result.current.error).toBe(failure));
  expect(apiClient.post).not.toHaveBeenCalled();
});

it.each([false, true])(
  "discards a completed old-scope readiness read (failed: %s)",
  async (failed) => {
    const pending = Promise.withResolvers<ConversationEnvironmentList>();
    vi.mocked(apiClient.get).mockReturnValueOnce(pending.promise);
    const { result, client } = setup(false);
    const previousRefresh = result.current.refresh;
    let response: ReturnType<typeof previousRefresh> | undefined;
    act(() => {
      response = previousRefresh();
    });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledOnce());
    act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
    await waitFor(() => expect(result.current.refresh).not.toBe(previousRefresh));
    await act(async () => {
      if (failed) pending.reject(new Error("Controlled old-scope refusal"));
      else pending.resolve(listed(first));
      expect(await response).toBeNull();
    });
    const nextKey = qk.conversationEnvironments.context("owner", "actor", "org-two", "chat", agent);
    expect(client.getQueryData(nextKey)).toBeUndefined();
    expect(result.current.items).toBeUndefined();
    expect(apiClient.get).toHaveBeenCalledOnce();
    expect(apiClient.post).not.toHaveBeenCalled();
  },
);
