import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./sandbox-workspaces-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "w-1" }], total: 1 });
});

describe("the workspace browser client", () => {
  it("unwraps the listing, because no caller wants the envelope", async () => {
    await expect(api.listWorkspaces()).resolves.toEqual([{ id: "w-1" }]);
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces");
  });

  it("reads one workspace's files by its own id", async () => {
    // Not through a conversation: a run-scoped workspace never had one and an
    // agent-scoped one belongs to all of them.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [] });

    await api.readWorkspaceFiles("w-1");

    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces/w-1/files");
  });

  it("escapes the path, because workspace paths contain slashes", async () => {
    // A path segment would need escaping this client has to get exactly right, so
    // it goes in a query parameter - encoded, or the slashes end the parameter.
    vi.mocked(apiClient.get).mockResolvedValue({ path: "/a/b.txt", content: "", truncated: false });

    await api.readWorkspaceFile("w-1", "/a/b.txt");

    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces/w-1/file?path=%2Fa%2Fb.txt");
  });

  it("asks for every file in one call, not one call per workspace", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      total: 0,
      workspaces_read: 0,
      unreadable: 0,
      truncated: false,
    });

    await api.listAllWorkspaceFiles();

    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces/files");
  });
});
