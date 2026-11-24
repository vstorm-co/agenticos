import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listConversationMessagePins,
  pinConversationMessage,
  unpinConversationMessage,
  type ConversationMessagePin,
} from "@/lib/conversation-message-pin-api";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useMessagePins } from "./use-message-pins";

const state = vi.hoisted(() => ({
  tenant: "org-1" as string | null,
  loadedConversationId: "c-1" as string | null,
  updateMessage: vi.fn(),
}));
const toast = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => state.tenant,
  useTenantGuard: () => (startedIn: string | null) => state.tenant === startedIn,
}));
vi.mock("@/lib/conversation-message-pin-api", () => ({
  listConversationMessagePins: vi.fn(),
  pinConversationMessage: vi.fn(),
  unpinConversationMessage: vi.fn(),
}));
vi.mock("@/stores", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/stores")>()),
  useChatStore: Object.assign(
    (selector: (value: { updateMessage: typeof state.updateMessage }) => unknown) =>
      selector({ updateMessage: state.updateMessage }),
    {
      useApi: () => ({
        getState: () => ({
          loadedTranscript: state.loadedConversationId
            ? { conversationId: state.loadedConversationId }
            : null,
        }),
      }),
    },
  ),
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("sonner", () => ({ toast }));

const user = {
  id: "person-1",
  email: "person@example.test",
  is_active: true,
  created_at: "2026-11-17T00:00:00Z",
};
let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.resetAllMocks();
  state.tenant = "org-1";
  state.loadedConversationId = "c-1";
  useAuthStore.setState({ user });
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(listConversationMessagePins).mockResolvedValue({
    items: [{ message_id: "m-1", thread_root_message_id: "root-1", preview: "Pinned" } as never],
    total: 1,
  });
  vi.mocked(pinConversationMessage).mockResolvedValue({ message_id: "m-2" } as never);
});

describe("useMessagePins", () => {
  it("waits for a signed-in reader, tenant, conversation and enabled panel", () => {
    const { result, rerender } = renderHook(
      ({ enabled, conversationId }: { enabled: boolean; conversationId: string | null }) =>
        useMessagePins(conversationId, enabled),
      { initialProps: { enabled: false, conversationId: null as string | null }, wrapper },
    );

    expect(listConversationMessagePins).not.toHaveBeenCalled();
    rerender({ enabled: true, conversationId: null });
    expect(result.current.items).toEqual([]);
    expect(listConversationMessagePins).not.toHaveBeenCalled();
    act(() => {
      state.tenant = null;
      useAuthStore.setState({ user: null });
      rerender({ enabled: true, conversationId: "c-1" });
    });
    expect(listConversationMessagePins).not.toHaveBeenCalled();
  });

  it("pages under the tenant, account and conversation key, preserving thread targets", async () => {
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(listConversationMessagePins).toHaveBeenCalledWith("c-1", 0, expect.any(AbortSignal));
    expect(result.current.items[0]).toMatchObject({
      message_id: "m-1",
      thread_root_message_id: "root-1",
    });
    expect(
      client.getQueryData(qk.conversations.messagePins("org-1", "person-1", "c-1")),
    ).toBeDefined();
  });

  it("loads the next bounded page only while pinned rows remain", async () => {
    vi.mocked(listConversationMessagePins)
      .mockResolvedValueOnce({
        items: [
          {
            message_id: "m-1",
            thread_root_message_id: null,
            role: "assistant",
            message_created_at: "2026-11-17T00:00:00Z",
            pinned_at: "2026-11-17T00:00:00Z",
            preview: "First",
          },
        ],
        total: 2,
      })
      .mockResolvedValueOnce({
        items: [
          {
            message_id: "m-2",
            thread_root_message_id: null,
            role: "assistant",
            message_created_at: "2026-11-17T00:00:00Z",
            pinned_at: "2026-11-17T00:00:00Z",
            preview: "Second",
          },
        ],
        total: 2,
      });
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(listConversationMessagePins).toHaveBeenNthCalledWith(
      2,
      "c-1",
      1,
      expect.any(AbortSignal),
    );
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.items.map((pin) => pin.message_id)).toEqual(["m-1", "m-2"]);
    expect(result.current.hasNextPage).toBe(false);
  });

  it("does not send a write when the captured reader scope changes before it starts", async () => {
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    act(() => {
      result.current.togglePin("m-2", true);
      state.tenant = "org-2";
      useAuthStore.setState({ user: { ...user, id: "person-2" } });
    });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));

    expect(pinConversationMessage).not.toHaveBeenCalled();
    expect(state.updateMessage).not.toHaveBeenCalled();
  });

  it("does not send a write for a signed-out or tenantless captured scope", async () => {
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string | null }) => useMessagePins(conversationId),
      { initialProps: { conversationId: null as string | null }, wrapper },
    );

    act(() => result.current.togglePin("m-2", true));
    expect(pinConversationMessage).not.toHaveBeenCalled();

    act(() => {
      state.tenant = null;
      rerender({ conversationId: "c-1" });
      result.current.togglePin("m-2", true);
    });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
    expect(pinConversationMessage).not.toHaveBeenCalled();
  });

  it("does not patch the chat after the account or tenant changes during a write", async () => {
    let settle!: (value: ConversationMessagePin) => void;
    vi.mocked(pinConversationMessage).mockImplementationOnce(
      () => new Promise<ConversationMessagePin>((resolve) => (settle = resolve)),
    );
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    act(() => result.current.togglePin("m-2", true));
    await waitFor(() => expect(pinConversationMessage).toHaveBeenCalledOnce());
    act(() => {
      state.tenant = "org-2";
      useAuthStore.setState({ user: { ...user, id: "person-2" } });
    });
    await act(async () =>
      settle({
        message_id: "m-2",
        thread_root_message_id: null,
        role: "assistant",
        message_created_at: "2026-11-17T00:00:00Z",
        pinned_at: "2026-11-17T00:00:00Z",
        preview: "Pinned",
      }),
    );

    expect(state.updateMessage).not.toHaveBeenCalled();
  });

  it("uses the conversation captured when the pin action was chosen", async () => {
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string }) => useMessagePins(conversationId),
      { initialProps: { conversationId: "c-1" }, wrapper },
    );

    act(() => result.current.togglePin("m-2", true));
    rerender({ conversationId: "c-2" });
    await waitFor(() => expect(pinConversationMessage).toHaveBeenCalledOnce());

    expect(pinConversationMessage).toHaveBeenCalledWith("c-1", "m-2");
  });

  it("serializes opposite toggles across hook instances in one reader scope", async () => {
    let finishPin!: (value: ConversationMessagePin) => void;
    let finishUnpin!: () => void;
    vi.mocked(pinConversationMessage).mockImplementationOnce(
      () => new Promise<ConversationMessagePin>((resolve) => (finishPin = resolve)),
    );
    vi.mocked(unpinConversationMessage).mockImplementationOnce(
      () => new Promise<void>((resolve) => (finishUnpin = resolve)),
    );
    const first = renderHook(() => useMessagePins("c-1", false), { wrapper });
    const second = renderHook(() => useMessagePins("c-1", true), { wrapper });

    act(() => {
      first.result.current.togglePin("m-2", true);
      second.result.current.togglePin("m-2", false);
    });

    await waitFor(() => expect(pinConversationMessage).toHaveBeenCalledOnce());
    expect(unpinConversationMessage).not.toHaveBeenCalled();
    const mutations = client.getMutationCache().getAll();
    expect(mutations).toHaveLength(2);
    expect(mutations.map((mutation) => mutation.options.scope?.id)).toEqual([
      JSON.stringify(["conversation-message-pin", "org-1", "person-1", "c-1"]),
      JSON.stringify(["conversation-message-pin", "org-1", "person-1", "c-1"]),
    ]);

    await act(async () =>
      finishPin({
        message_id: "m-2",
        thread_root_message_id: null,
        role: "assistant",
        message_created_at: "2026-11-17T00:00:00Z",
        pinned_at: "2026-11-17T00:00:00Z",
        preview: "Pinned",
      }),
    );
    await waitFor(() => expect(unpinConversationMessage).toHaveBeenCalledOnce());
    await act(async () => finishUnpin());

    expect(vi.mocked(pinConversationMessage).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(unpinConversationMessage).mock.invocationCallOrder[0]!,
    );
  });

  it("updates only the current conversation message and invalidates its list after success", async () => {
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    act(() => result.current.togglePin("m-2", true));
    await waitFor(() => expect(state.updateMessage).toHaveBeenCalledOnce());
    const update = state.updateMessage.mock.calls[0]![1] as (message: {
      conversationId: string;
      isPinned?: boolean;
    }) => { conversationId: string; isPinned?: boolean };
    expect(update({ conversationId: "c-1" })).toMatchObject({ isPinned: true });
    expect(update({ conversationId: "c-2" })).toEqual({ conversationId: "c-2" });
  });

  it("unpins with the captured scope and reports an API failure to the current reader", async () => {
    let settle!: () => void;
    vi.mocked(unpinConversationMessage).mockImplementationOnce(
      () => new Promise<void>((resolve) => (settle = resolve)),
    );
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    act(() => result.current.togglePin("m-2", false));
    await waitFor(() => expect(unpinConversationMessage).toHaveBeenCalledWith("c-1", "m-2"));
    expect(result.current.pendingMessageId).toBe("m-2");
    await act(async () => settle());
    await waitFor(() => expect(state.updateMessage).toHaveBeenCalledOnce());
    const update = state.updateMessage.mock.calls[0]![1] as (message: {
      conversationId: string;
      isPinned?: boolean;
    }) => { conversationId: string; isPinned?: boolean };
    expect(update({ conversationId: "c-1", isPinned: true })).toMatchObject({ isPinned: false });

    vi.mocked(unpinConversationMessage).mockRejectedValueOnce(new Error("unpin failed"));
    act(() => result.current.togglePin("m-3", false));
    await waitFor(() => expect(toast.error).toHaveBeenCalledOnce());
  });

  it("does not notify a different reader when a pin mutation fails", async () => {
    let fail!: (error: Error) => void;
    vi.mocked(pinConversationMessage).mockImplementationOnce(
      () => new Promise<ConversationMessagePin>((_resolve, reject) => (fail = reject)),
    );
    const { result } = renderHook(() => useMessagePins("c-1"), { wrapper });

    act(() => result.current.togglePin("m-2", true));
    await waitFor(() => expect(pinConversationMessage).toHaveBeenCalledOnce());
    act(() => useAuthStore.setState({ user: { ...user, id: "person-2" } }));
    await act(async () => fail(new Error("pin failed")));
    await waitFor(() => expect(result.current.pendingMessageId).toBeNull());

    expect(toast.error).not.toHaveBeenCalled();
  });

  it("does not toast a pin failure after the scoped transcript changes", async () => {
    let fail!: (error: Error) => void;
    vi.mocked(pinConversationMessage).mockImplementationOnce(
      () => new Promise<ConversationMessagePin>((_resolve, reject) => (fail = reject)),
    );
    const { result, rerender } = renderHook(
      ({ conversationId }: { conversationId: string }) => useMessagePins(conversationId),
      { initialProps: { conversationId: "c-1" }, wrapper },
    );

    act(() => result.current.togglePin("m-2", true));
    await waitFor(() => expect(pinConversationMessage).toHaveBeenCalledOnce());
    act(() => {
      state.loadedConversationId = "c-2";
      rerender({ conversationId: "c-2" });
    });
    await act(async () => fail(new Error("pin failed")));

    expect(toast.error).not.toHaveBeenCalled();
  });
});
