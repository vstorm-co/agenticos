import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";
import { useConversationStore } from "@/stores/conversation-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Conversation } from "@/types/conversation";
import { useEnvironmentConversation } from "./use-environment-conversation";

const created: Conversation = {
  id: "33333333-3333-4333-8333-333333333333",
  created_at: "2026-11-27T10:00:00Z",
  updated_at: null,
  is_archived: false,
};

function deferred() {
  let resolve!: (value: Conversation | null) => void;
  const promise = new Promise<Conversation | null>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

beforeEach(() => {
  useAuthStore.setState({
    sessionOwnerId: "owner",
    user: { id: "actor", email: "reader@example.com", is_active: true, created_at: "2026-01-01" },
  });
  useOrgStore.setState({ activeOrgId: "org-one" });
  useAgentSelectionStore.getState().select("agent-one");
  useConversationStore.getState().reset();
  useWorkOnStore.getState().resetDraft();
});

it("reuses the current conversation without creating or sending anything", async () => {
  useConversationStore.getState().setCurrentConversationId(created.id);
  const create = vi.fn();
  const { result } = renderHook(() => useEnvironmentConversation(create));
  await expect(result.current.prepare()).resolves.toBe(created.id);
  expect(create).not.toHaveBeenCalled();
});

it("files an empty project chat and keeps its local choices without a model call", async () => {
  useConversationStore.getState().setPendingProjectId("project-one");
  useWorkOnStore.getState().setBrowser(null, true);
  const create = vi.fn().mockResolvedValue({ ...created, project_id: "project-one" });
  const { result } = renderHook(() => useEnvironmentConversation(create));
  await act(async () => {
    expect(await result.current.prepare()).toBe(created.id);
  });
  expect(create).toHaveBeenCalledWith(undefined, { projectId: "project-one" });
  expect(useConversationStore.getState().currentConversationId).toBe(created.id);
  expect(useConversationStore.getState().createdConversationId).toBe(created.id);
  expect(useConversationStore.getState().pendingProjectId).toBeNull();
  expect(useWorkOnStore.getState().browserFor(created.id)).toBe(true);
});

it("shares an in-flight creation between repeated opens", async () => {
  const pending = deferred();
  const create = vi.fn().mockReturnValue(pending.promise);
  const { result } = renderHook(() => useEnvironmentConversation(create));
  let first!: Promise<string | null>;
  let second!: Promise<string | null>;
  act(() => {
    first = result.current.prepare();
    second = result.current.prepare();
  });
  expect(first).toBe(second);
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  expect(result.current.preparing).toBe(true);
  await act(async () => {
    pending.resolve(created);
    await first;
  });
  expect(result.current.preparing).toBe(false);
});

it.each(["organization", "project", "agent"])(
  "does not adopt an old %s's delayed response",
  async (kind) => {
    const pending = deferred();
    const create = vi.fn().mockReturnValue(pending.promise);
    const { result } = renderHook(() => useEnvironmentConversation(create));
    let opening!: Promise<string | null>;
    act(() => {
      opening = result.current.prepare();
    });
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    act(() => {
      if (kind === "organization") useOrgStore.setState({ activeOrgId: "org-two" });
      if (kind === "project") useConversationStore.getState().setPendingProjectId("other-project");
      if (kind === "agent") useAgentSelectionStore.getState().select("other-agent");
    });
    await act(async () => {
      pending.resolve(created);
      expect(await opening).toBeNull();
    });
    expect(useConversationStore.getState().currentConversationId).toBeNull();
  },
);

it("does not adopt a delayed response after leaving the chat", async () => {
  const pending = deferred();
  const create = vi.fn().mockReturnValue(pending.promise);
  const { result, unmount } = renderHook(() => useEnvironmentConversation(create));
  let opening!: Promise<string | null>;
  act(() => {
    opening = result.current.prepare();
  });
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  unmount();
  pending.resolve(created);
  await expect(opening).resolves.toBeNull();
  expect(useConversationStore.getState().currentConversationId).toBeNull();
});

it("releases the creation guard even when the adapter throws synchronously", async () => {
  const failed = new Error("refused");
  const create = vi
    .fn()
    .mockImplementationOnce(() => {
      throw failed;
    })
    .mockResolvedValue(created);
  const { result } = renderHook(() => useEnvironmentConversation(create));
  await act(async () => {
    await expect(result.current.prepare()).rejects.toBe(failed);
  });
  expect(result.current.preparing).toBe(false);
  await act(async () => {
    await expect(result.current.prepare()).resolves.toBe(created.id);
  });
  expect(create).toHaveBeenCalledTimes(2);
});

it("does not replace a conversation selected while creation was pending", async () => {
  const pending = deferred();
  const create = vi.fn().mockReturnValue(pending.promise);
  const { result } = renderHook(() => useEnvironmentConversation(create));
  let opening!: Promise<string | null>;
  act(() => {
    opening = result.current.prepare();
  });
  await waitFor(() => expect(create).toHaveBeenCalledOnce());
  act(() => useConversationStore.getState().setCurrentConversationId("another-chat"));
  await act(async () => {
    pending.resolve(created);
    expect(await opening).toBeNull();
  });
  expect(useConversationStore.getState().currentConversationId).toBe("another-chat");
});

it("does not start a request after the tenant changes before deferred admission", async () => {
  const create = vi.fn().mockResolvedValue(created);
  const { result } = renderHook(() => useEnvironmentConversation(create));
  let opening!: Promise<string | null>;
  act(() => {
    opening = result.current.prepare();
    useOrgStore.setState({ activeOrgId: "new-org" });
  });
  await act(async () => {
    expect(await opening).toBeNull();
  });
  expect(create).not.toHaveBeenCalled();
});

it("refuses a callback from an old selection or unmounted view", async () => {
  const create = vi.fn().mockResolvedValue(created);
  const { result, unmount } = renderHook(() => useEnvironmentConversation(create));
  const oldPrepare = result.current.prepare;
  act(() => useAgentSelectionStore.getState().select("new-agent"));
  await expect(oldPrepare()).resolves.toBeNull();
  const currentPrepare = result.current.prepare;
  unmount();
  await expect(currentPrepare()).resolves.toBeNull();
  expect(create).not.toHaveBeenCalled();
});

it("keeps the draft when creation is refused for a direct signed-in session", async () => {
  useAuthStore.setState({ sessionOwnerId: null });
  const create = vi.fn().mockResolvedValue(null);
  const { result } = renderHook(() => useEnvironmentConversation(create));
  await act(async () => {
    expect(await result.current.prepare()).toBeNull();
  });
  expect(useConversationStore.getState().currentConversationId).toBeNull();
  expect(result.current.preparing).toBe(false);
});
