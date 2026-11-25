import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useConversationWorkspace } from "./use-conversation-workspace";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({
    scope: "conversation",
    backend: "state",
    owner_label: "This conversation",
    items: [{ path: "/report.csv", size: 42, is_dir: false }],
    total: 1,
    bytes_total: 42,
  });
});

/**
 * The client half of the conversation's workspace listing.
 *
 * The property worth holding is that it asks for nothing before there is something to
 * ask about: a new chat has no conversation id. Reading one of these *files* is
 * `use-workspace-file.test.tsx`, which covers both addresses a file can have.
 */
describe("the files one conversation is keeping", () => {
  it("does not ask before a conversation exists", () => {
    const { result } = renderHook(() => useConversationWorkspace(null), { wrapper });

    expect(apiClient.get).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reads the workspace of the conversation on screen", async () => {
    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });

    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c1/workspace");
    expect(result.current.workspace?.items).toHaveLength(1);
  });

  it("re-reads on demand, because a turn is what changes the files", async () => {
    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());

    await act(async () => {
      await result.current.refresh();
    });

    expect(vi.mocked(apiClient.get).mock.calls).toHaveLength(2);
  });

  it("refreshing a conversation that does not exist asks for nothing", async () => {
    const { result } = renderHook(() => useConversationWorkspace(null), { wrapper });

    await act(async () => {
      await result.current.refresh();
    });

    expect(apiClient.get).not.toHaveBeenCalled();
  });

  it("reports a refusal rather than an empty workspace", async () => {
    // An agent that keeps no files and a request that answered 403 are the same
    // pixels otherwise, and only one of them is worth telling somebody about.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("Not permitted"));

    const { result } = renderHook(() => useConversationWorkspace("c1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not permitted"));
    expect(result.current.workspace).toBeNull();
  });
});

import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  workspaceOriginKey,
  type ConversationWorkspaceOrigin,
  type ConversationWorkspaceOrigins,
} from "@/lib/conversation-workspace-api";

const agentOrigin: ConversationWorkspaceOrigin = {
  kind: "agent",
  workspace_id: "agent-space",
  project_id: null,
  scope: "agent",
  backend: "state",
  owner_label: "Research agent",
};
const projectOrigin: ConversationWorkspaceOrigin = {
  kind: "project",
  workspace_id: "project-space",
  project_id: "project-1",
  scope: "project",
  backend: "state",
  owner_label: "Research project",
};
function inventory(items = [agentOrigin, projectOrigin]): ConversationWorkspaceOrigins {
  return {
    default_origin: "project",
    default_workspace_id: "project-space",
    items,
    truncated: false,
  };
}

describe("explicit chat file origins", () => {
  beforeEach(() => {
    useAuthStore.setState({ sessionOwnerId: "reader-1" });
    useOrgStore.setState({ activeOrgId: "org-1" });
  });

  function mockOrigins(initial = inventory()) {
    const state = { inventory: initial, refused: false };
    vi.mocked(apiClient.get).mockImplementation(async (url) => {
      if (url.endsWith("workspace-origins")) {
        if (state.refused) throw new Error("Conversation not available");
        return state.inventory;
      }
      return {
        scope: "project",
        backend: "state",
        owner_label: url,
        items: [{ path: "/same.txt", size: 10, is_dir: false, modified_at: null }],
        bytes_total: 10,
        total: 1,
        unreadable_reason: null,
        truncated: false,
      };
    });
    return state;
  }

  it("selects only the server's exact default and lists the project endpoint", async () => {
    mockOrigins();
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    expect(result.current.source).toEqual({ kind: "project", id: "project-1" });
    expect(apiClient.get).toHaveBeenCalledWith("/projects/project-1/files");
    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/c1/workspace");
    expect(result.current.workspace?.items[0]?.preview).toBeNull();
    expect(result.current.contentKey).toContain("reader-1");
    expect(result.current.contentKey).toContain("org-1");
  });

  it("uses a different source for the same path and keeps the explicit choice after refresh", async () => {
    mockOrigins();
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    const firstKey = result.current.contentKey;
    act(() => result.current.selectOrigin(workspaceOriginKey(agentOrigin)));
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces/agent-space/files"),
    );
    expect(result.current.source).toEqual({ kind: "workspace", id: "agent-space" });
    expect(result.current.contentKey).not.toEqual(firstKey);
    await act(() => result.current.refresh());
    expect(result.current.selectedOrigin).toEqual(agentOrigin);
  });

  it("removes a revoked location without switching source, then accepts an explicit choice", async () => {
    const state = mockOrigins();
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    state.inventory = {
      ...inventory([agentOrigin]),
      default_origin: "agent",
      default_workspace_id: "agent-space",
    };
    await act(() => result.current.refresh());
    await waitFor(() => expect(result.current.originUnavailable).toBe(true));
    expect(result.current.source).toBeNull();
    expect(result.current.workspace).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/sandbox-workspaces/agent-space/files");
    act(() => result.current.selectOrigin(workspaceOriginKey(agentOrigin)));
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
  });

  it("clears cached listing on refusal without falling back to the legacy route", async () => {
    const state = mockOrigins();
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    state.refused = true;
    await act(() => result.current.refresh());
    await waitFor(() => expect(result.current.error).toBe("Conversation not available"));
    expect(result.current.workspace).toBeNull();
    expect(result.current.source).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/c1/workspace");
  });

  it("isolates the inventory, listing and preview keys by owner and organization", async () => {
    mockOrigins();
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    const key = result.current.contentKey;
    act(() => {
      useAuthStore.setState({ sessionOwnerId: "reader-2" });
      useOrgStore.setState({ activeOrgId: "org-2" });
    });
    expect(result.current.workspace).toBeNull();
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    expect(result.current.contentKey).not.toEqual(key);
    expect(result.current.contentKey).toContain("reader-2");
  });

  it("preserves the legacy route for a successfully empty initial inventory", async () => {
    mockOrigins({ default_origin: null, default_workspace_id: null, items: [], truncated: false });
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.workspace).not.toBeNull());
    expect(result.current.source).toEqual({ kind: "conversation", id: "c1" });
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c1/workspace");
  });

  it("waits for the owner and refuses malformed or unknown project choices", async () => {
    mockOrigins(inventory([{ ...projectOrigin, project_id: null }]));
    useAuthStore.setState({ sessionOwnerId: null, user: null });
    const { result } = renderHook(() => useConversationWorkspace("c1", { originPicker: true }), {
      wrapper,
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    act(() => useAuthStore.setState({ sessionOwnerId: "reader-1" }));
    await waitFor(() => expect(result.current.originUnavailable).toBe(true));
    act(() => result.current.selectOrigin("unknown-origin"));
    expect(result.current.source).toBeNull();
    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/c1/workspace");
  });
});
