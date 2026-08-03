import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  downloadWorkspaceFile,
  useAllWorkspaceFiles,
  useWorkspaceBytes,
  useSandboxWorkspaces,
  useWorkspaceFile,
  useWorkspaceFiles,
} from "./use-sandbox-workspaces";
import * as api from "@/lib/sandbox-workspaces-api";
import type { WorkspaceSummary } from "@/lib/sandbox-workspaces-api";

vi.mock("@/lib/sandbox-workspaces-api", () => ({
  listWorkspaces: vi.fn(),
  listAllWorkspaceFiles: vi.fn(),
  readWorkspaceBytes: vi.fn(),
  readWorkspaceFiles: vi.fn(),
  readWorkspaceFile: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const WORKSPACE: WorkspaceSummary = {
  id: "w-1",
  agent_id: "a-1",
  agent_name: "Analyst",
  conversation_id: "c-1",
  conversation_title: "Refund policy",
  conversations: 1,
  scope: "conversation",
  backend: "state",
  owner_label: "This conversation",
  access_label: "Whoever is in that conversation",
  bytes_total: 2048,
  version: 1,
  last_used_at: null,
  created_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listWorkspaces).mockResolvedValue([WORKSPACE]);
  vi.mocked(api.readWorkspaceFiles).mockResolvedValue({
    scope: "conversation",
    unreadable_reason: null,
    backend: "state",
    owner_label: "This conversation",
    items: [],
    total: 0,
    bytes_total: 2048,
  });
  vi.mocked(api.readWorkspaceFile).mockResolvedValue({
    path: "/a.txt",
    content: "hello",
    truncated: false,
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

describe("useWorkspaceFile", () => {
  it("reads the file it was given", async () => {
    const { result } = renderHook(() => useWorkspaceFile("w-1", "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.file?.content).toBe("hello"));
    expect(api.readWorkspaceFile).toHaveBeenCalledWith("w-1", "/a.txt");
  });

  it("reads nothing until a file is opened", () => {
    const { result } = renderHook(() => useWorkspaceFile("w-1", null), { wrapper });

    expect(api.readWorkspaceFile).not.toHaveBeenCalled();
    expect(result.current.isLoading).toBe(false);
  });

  it("reports one that could not be read", async () => {
    vi.mocked(api.readWorkspaceFile).mockRejectedValue(new Error("404 Not Found"));
    const { result } = renderHook(() => useWorkspaceFile("w-1", "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("404 Not Found"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(api.readWorkspaceFile).mockRejectedValue("nope");
    const { result } = renderHook(() => useWorkspaceFile("w-1", "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("That file could not be read"));
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

describe("one file's bytes", () => {
  const created: string[] = [];
  const revoked: string[] = [];

  beforeEach(() => {
    created.length = 0;
    revoked.length = 0;
    // jsdom has neither, and the hook's whole job is to make and release one.
    Object.assign(URL, {
      createObjectURL: (blob: Blob) => {
        const url = `blob:${created.length}`;
        created.push(url);
        void blob;
        return url;
      },
      revokeObjectURL: (url: string) => revoked.push(url),
    });
    vi.mocked(api.readWorkspaceBytes).mockResolvedValue(new Blob(["bytes"]));
  });

  it("asks for nothing until there is a file to ask about", () => {
    renderHook(() => useWorkspaceBytes(null, null), { wrapper });

    expect(api.readWorkspaceBytes).not.toHaveBeenCalled();
  });

  it("answers with a URL something can render", async () => {
    // Not an `<img src>` pointing at the API: a browser request carries no
    // organization header, so the backend would answer for the wrong tenant.
    const { result } = renderHook(() => useWorkspaceBytes("w-1", "/chart.png"), { wrapper });

    await waitFor(() => expect(result.current.url).toBe("blob:0"));
    expect(api.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/chart.png");
  });

  it("releases the URL when it is done with it", async () => {
    // A blob URL holds the bytes alive until it is revoked, and an image the size of
    // a chart adds up over a session of clicking through files.
    const { result, unmount } = renderHook(() => useWorkspaceBytes("w-1", "/chart.png"), {
      wrapper,
    });
    await waitFor(() => expect(result.current.url).toBe("blob:0"));

    unmount();

    expect(revoked).toEqual(["blob:0"]);
  });

  it("reports a refusal rather than a blank preview", async () => {
    vi.mocked(api.readWorkspaceBytes).mockRejectedValue(new Error("This host can only read text"));

    const { result } = renderHook(() => useWorkspaceBytes("w-1", "/chart.png"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("This host can only read text"));
    expect(result.current.url).toBeNull();
  });
});

describe("saving a file to disk", () => {
  it("asks for it as a download and names it after the file", async () => {
    const clicked: HTMLAnchorElement[] = [];
    Object.assign(URL, {
      createObjectURL: () => "blob:download",
      revokeObjectURL: vi.fn(),
    });
    vi.mocked(api.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => clicked.push(element);
      return element;
    });

    await downloadWorkspaceFile("w-1", "/out/report.csv");

    expect(api.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/out/report.csv", {
      download: true,
    });
    expect(clicked[0]?.download).toBe("report.csv");
    vi.mocked(document.createElement).mockRestore();
  });

  it("keeps the URL alive until the browser has read it", async () => {
    // Firefox and Safari read a blob URL after the click handler returns, so
    // revoking synchronously cancels the download - and Chrome tolerates it, which is
    // how that ships broken for half the users.
    const revoked: string[] = [];
    Object.assign(URL, {
      createObjectURL: () => "blob:deferred",
      revokeObjectURL: (url: string) => revoked.push(url),
    });
    vi.mocked(api.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => {};
      return element;
    });

    await downloadWorkspaceFile("w-1", "/report.csv");

    // Filtered to this test's own URL: a deferred revoke from an earlier test lands
    // in whichever array is current when its timer fires.
    expect(revoked).not.toContain("blob:deferred");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(revoked).toContain("blob:deferred");
    vi.mocked(document.createElement).mockRestore();
  });

  it("falls back to a name when the path ends in a slash", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(api.readWorkspaceBytes).mockResolvedValue(new Blob([""]));
    const create = document.createElement.bind(document);
    const names: string[] = [];
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => names.push(element.download);
      return element;
    });

    await downloadWorkspaceFile("w-1", "/");

    expect(names).toContain("file");
    vi.mocked(document.createElement).mockRestore();
  });
});
