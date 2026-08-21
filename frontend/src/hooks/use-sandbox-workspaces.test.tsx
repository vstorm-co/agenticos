import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useAllWorkspaceFiles,
  useSandboxWorkspaces,
  useWorkspaceFiles,
} from "./use-sandbox-workspaces";
import * as api from "@/lib/sandbox-workspaces-api";
import type { WorkspaceSummary } from "@/lib/sandbox-workspaces-api";

vi.mock("@/lib/sandbox-workspaces-api", () => ({
  listWorkspaces: vi.fn(),
  listAllWorkspaceFiles: vi.fn(),
  readWorkspaceFiles: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const WORKSPACE: WorkspaceSummary = {
  id: "w-1",
  agent_id: "a-1",
  agent_name: "Analyst",
  agent_has_avatar: false,
  conversation_id: "c-1",
  conversation_is_mine: false,
  conversation_title: "Refund policy",
  conversations: 1,
  scope: "conversation",
  backend: "state",
  owner_label: "This conversation",
  access_label: "Whoever is in that conversation",
  bytes_total: 2048,
  file_count: 2,
  measured_bytes: 2048,
  version: 1,
  last_used_at: null,
  created_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listWorkspaces).mockResolvedValue({
    items: [WORKSPACE],
    total: 1,
    measured: 1,
    unreadable: 0,
    truncated: false,
  });
  vi.mocked(api.readWorkspaceFiles).mockResolvedValue({
    scope: "conversation",
    unreadable_reason: null,
    truncated: false,
    backend: "state",
    owner_label: "This conversation",
    items: [],
    total: 0,
    bytes_total: 2048,
  });
});

describe("useSandboxWorkspaces", () => {
  it("lists what the organization's agents are keeping", async () => {
    const { result } = renderHook(() => useSandboxWorkspaces(), { wrapper });

    await waitFor(() => expect(result.current.workspaces).toHaveLength(1));
    expect(result.current.error).toBeNull();
  });

  it("says why the list is empty rather than looking like nothing is kept", async () => {
    vi.mocked(api.listWorkspaces).mockRejectedValue(new Error("403 Forbidden"));
    const { result } = renderHook(() => useSandboxWorkspaces(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("403 Forbidden"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.listWorkspaces).mockRejectedValue("nope");
    const { result } = renderHook(() => useSandboxWorkspaces(), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Failed to load workspaces"));
  });
});

describe("useWorkspaceFiles", () => {
  it("reads the workspace it was given", async () => {
    const { result } = renderHook(() => useWorkspaceFiles("w-1"), { wrapper });

    await waitFor(() => expect(result.current.files).not.toBeNull());
    expect(api.readWorkspaceFiles).toHaveBeenCalledWith("w-1");
  });

  it("reads nothing until one is opened", () => {
    // Which is the whole reason the listing carries no files: this is a request
    // per workspace, and for a container-backed one it reads the host volume.
    const { result } = renderHook(() => useWorkspaceFiles(null), { wrapper });

    expect(api.readWorkspaceFiles).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reports one that could not be read", async () => {
    vi.mocked(api.readWorkspaceFiles).mockRejectedValue(new Error("did not answer"));
    const { result } = renderHook(() => useWorkspaceFiles("w-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("did not answer"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.readWorkspaceFiles).mockRejectedValue("nope");
    const { result } = renderHook(() => useWorkspaceFiles("w-1"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("That workspace could not be read"));
  });
});

describe("every file at once", () => {
  it("is not asked for until the flat view is on", () => {
    // It reads each workspace in turn - a round trip per container-backed one.
    renderHook(() => useAllWorkspaceFiles(false), { wrapper });

    expect(api.listAllWorkspaceFiles).not.toHaveBeenCalled();
  });

  it("carries what the answer left out", async () => {
    vi.mocked(api.listAllWorkspaceFiles).mockResolvedValue({
      items: [],
      total: 0,
      workspaces_read: 25,
      unreadable: 1,
      truncated: true,
    });

    const { result } = renderHook(() => useAllWorkspaceFiles(true), { wrapper });

    await waitFor(() => expect(result.current.listing).not.toBeNull());
    expect(result.current.listing?.truncated).toBe(true);
  });

  it("reports a refusal rather than an empty list", async () => {
    vi.mocked(api.listAllWorkspaceFiles).mockRejectedValue(new Error("Not permitted"));

    const { result } = renderHook(() => useAllWorkspaceFiles(true), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("Not permitted"));
  });
});
