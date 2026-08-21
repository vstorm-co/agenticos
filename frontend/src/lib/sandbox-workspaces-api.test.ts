import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./sandbox-workspaces-api";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({ apiClient: { get: vi.fn(), raw: vi.fn() } }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [{ id: "w-1" }], total: 1 });
});

describe("the workspace browser client", () => {
  it("keeps the envelope, because it says what counting left out", async () => {
    // It used to unwrap to `items`. The listing now reports how many workspaces it
    // read, how many hosts stayed silent and whether it stopped short - and a row
    // reading `-` because its host was down is otherwise indistinguishable from a
    // workspace holding nothing.
    const envelope = { items: [{ id: "w-1" }], total: 1, measured: 1, unreadable: 0 };
    vi.mocked(apiClient.get).mockResolvedValue(envelope);

    await expect(api.listWorkspaces()).resolves.toEqual(envelope);
    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces");
  });

  it("asks the hosts to be counted only when told to", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [] });

    await api.listWorkspaces(true);

    expect(apiClient.get).toHaveBeenCalledWith("/sandbox-workspaces?measure=true");
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

  it("asks for bytes through the client, so the organization header goes with them", async () => {
    // A bare browser request carries none, and the backend would then answer for the
    // caller's personal organization rather than the one on screen.
    const blob = new Blob(["a,b"]);
    vi.mocked(apiClient.raw).mockResolvedValue({ blob: async () => blob } as Response);

    await expect(api.readWorkspaceBytes("w-1", "/out/report.csv")).resolves.toBe(blob);
    expect(apiClient.raw).toHaveBeenCalledWith(
      "/sandbox-workspaces/w-1/raw?path=%2Fout%2Freport.csv",
    );
  });

  it("says when it wants a download rather than a preview", async () => {
    vi.mocked(apiClient.raw).mockResolvedValue({
      blob: async () => new Blob([""]),
    } as Response);

    await api.readWorkspaceBytes("w-1", "/chart.png", { download: true });

    expect(apiClient.raw).toHaveBeenCalledWith(
      "/sandbox-workspaces/w-1/raw?path=%2Fchart.png&download=true",
    );
  });
});
