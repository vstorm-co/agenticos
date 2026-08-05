import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  downloadWorkspaceFile,
  useFileDownload,
  useWorkspaceFileBytes,
  useWorkspaceFileText,
} from "./use-workspace-file";
import * as conversationApi from "@/lib/conversation-workspace-api";
import * as workspaceApi from "@/lib/sandbox-workspaces-api";
import type { FileSource } from "@/lib/workspace-files";

vi.mock("@/lib/conversation-workspace-api", () => ({
  readConversationFile: vi.fn(),
  readConversationFileBytes: vi.fn(),
}));
vi.mock("@/lib/sandbox-workspaces-api", () => ({
  readWorkspaceFile: vi.fn(),
  readWorkspaceBytes: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const IN_CHAT: FileSource = { kind: "conversation", id: "c-1" };
const IN_WORKSPACE: FileSource = { kind: "workspace", id: "w-1" };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(conversationApi.readConversationFile).mockResolvedValue({
    path: "/a.txt",
    content: "hello",
    truncated: false,
  });
  vi.mocked(workspaceApi.readWorkspaceFile).mockResolvedValue({
    path: "/a.txt",
    content: "hello",
    truncated: false,
  });
});

/**
 * One file, read through whichever address the surface has.
 *
 * The chat panel holds a conversation and the Workspaces screen holds a workspace id,
 * and they are not interchangeable: the conversation route also admits somebody the
 * chat was shared with. One hook, so the viewer above it cannot end up with a
 * different set of behaviours per surface.
 */
describe("one file's text", () => {
  it("reads a chat's file through its conversation", async () => {
    const { result } = renderHook(() => useWorkspaceFileText(IN_CHAT, "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.file?.content).toBe("hello"));
    expect(conversationApi.readConversationFile).toHaveBeenCalledWith("c-1", "/a.txt");
    expect(workspaceApi.readWorkspaceFile).not.toHaveBeenCalled();
  });

  it("reads a workspace's file through its id", async () => {
    const { result } = renderHook(() => useWorkspaceFileText(IN_WORKSPACE, "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.file?.content).toBe("hello"));
    expect(workspaceApi.readWorkspaceFile).toHaveBeenCalledWith("w-1", "/a.txt");
  });

  it("reports one that could not be read", async () => {
    vi.mocked(workspaceApi.readWorkspaceFile).mockRejectedValue(new Error("404 Not Found"));
    const { result } = renderHook(() => useWorkspaceFileText(IN_WORKSPACE, "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("404 Not Found"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(workspaceApi.readWorkspaceFile).mockRejectedValue("nope");
    const { result } = renderHook(() => useWorkspaceFileText(IN_WORKSPACE, "/a.txt"), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("That file could not be read"));
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
      createObjectURL: () => {
        const url = `blob:${created.length}`;
        created.push(url);
        return url;
      },
      revokeObjectURL: (url: string) => revoked.push(url),
    });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(
      new Blob(["bytes"], { type: "image/png" }),
    );
    vi.mocked(conversationApi.readConversationFileBytes).mockResolvedValue(
      new Blob(["%PDF-"], { type: "application/pdf" }),
    );
  });

  it("answers with a URL something can render", async () => {
    // Not an `<img src>` or an `<iframe src>` pointing at the API: a browser request
    // carries no organization header, so the backend would answer for the wrong tenant.
    const { result } = renderHook(() => useWorkspaceFileBytes(IN_WORKSPACE, "/chart.png"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.url).toBe("blob:0"));
    expect(workspaceApi.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/chart.png", {});
  });

  it("says what the server called it, so a viewer does not guess from the suffix", async () => {
    // The API decides what may be shown inline. A client list of suffixes deciding it
    // too is a second answer, and when the two disagreed an `<img>` got a blob typed
    // `application/octet-stream` and showed a broken image with nothing saying why.
    const { result } = renderHook(() => useWorkspaceFileBytes(IN_CHAT, "/report.pdf"), { wrapper });

    await waitFor(() => expect(result.current.mediaType).toBe("application/pdf"));
  });

  it("releases the URL when it is done with it", async () => {
    // A blob URL holds the bytes alive until it is revoked, and a PDF or a chart adds
    // up over a session of clicking through files.
    const { result, unmount } = renderHook(
      () => useWorkspaceFileBytes(IN_WORKSPACE, "/chart.png"),
      { wrapper },
    );
    await waitFor(() => expect(result.current.url).toBe("blob:0"));

    unmount();

    expect(revoked).toEqual(["blob:0"]);
  });

  it("reports a refusal rather than a blank preview", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(
      new Error("This host can only read text"),
    );

    const { result } = renderHook(() => useWorkspaceFileBytes(IN_WORKSPACE, "/chart.png"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.error).toBe("This host can only read text"));
    expect(result.current.url).toBeNull();
  });
});

describe("saving a file to disk", () => {
  it("asks for it as a download and names it after the file", async () => {
    const clicked: HTMLAnchorElement[] = [];
    Object.assign(URL, { createObjectURL: () => "blob:download", revokeObjectURL: vi.fn() });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => clicked.push(element);
      return element;
    });

    await downloadWorkspaceFile(IN_WORKSPACE, "/out/report.csv");

    expect(workspaceApi.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/out/report.csv", {
      download: true,
    });
    expect(clicked[0]?.download).toBe("report.csv");
    vi.mocked(document.createElement).mockRestore();
  });

  it("saves a chat's file through the conversation route", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:chat", revokeObjectURL: vi.fn() });
    vi.mocked(conversationApi.readConversationFileBytes).mockResolvedValue(new Blob(["%PDF-"]));
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => {};
      return element;
    });

    await downloadWorkspaceFile(IN_CHAT, "/report.pdf");

    expect(conversationApi.readConversationFileBytes).toHaveBeenCalledWith("c-1", "/report.pdf", {
      download: true,
    });
    vi.mocked(document.createElement).mockRestore();
  });

  it("keeps the URL alive until the browser has read it", async () => {
    // Firefox and Safari read a blob URL after the click handler returns, so revoking
    // synchronously cancels the download - and Chrome tolerates it, which is how that
    // ships broken for half the users.
    const revoked: string[] = [];
    Object.assign(URL, {
      createObjectURL: () => "blob:deferred",
      revokeObjectURL: (url: string) => revoked.push(url),
    });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));
    const create = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => {};
      return element;
    });

    await downloadWorkspaceFile(IN_WORKSPACE, "/report.csv");

    expect(revoked).not.toContain("blob:deferred");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(revoked).toContain("blob:deferred");
    vi.mocked(document.createElement).mockRestore();
  });

  it("falls back to a name when the path ends in a slash", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob([""]));
    const create = document.createElement.bind(document);
    const names: string[] = [];
    vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
      const element = create(tag) as HTMLAnchorElement;
      if (tag === "a") element.click = () => names.push(element.download);
      return element;
    });

    await downloadWorkspaceFile(IN_WORKSPACE, "/");

    expect(names).toContain("file");
    vi.mocked(document.createElement).mockRestore();
  });
});

describe("a download that is refused", () => {
  it("says why, rather than looking like a button that does nothing", async () => {
    // The certain case: a binary in a container-backed workspace is read through an
    // archive that can only read text, so the API answers 400. A bare `void
    // download(...)` dropped that on the floor.
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(
      new Error("This host can only read text"),
    );
    const { result } = renderHook(() => useFileDownload(IN_WORKSPACE), { wrapper });

    result.current.download("/chart.png");

    await waitFor(() => expect(result.current.error).toBe("This host can only read text"));
  });

  it("clears the last refusal when a new attempt starts", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(new Error("nope"));
    const { result } = renderHook(() => useFileDownload(IN_WORKSPACE), { wrapper });
    result.current.download("/chart.png");
    await waitFor(() => expect(result.current.error).toBe("nope"));
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));

    result.current.download("/report.csv");

    await waitFor(() => expect(result.current.error).toBeNull());
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue("nope");
    const { result } = renderHook(() => useFileDownload(IN_WORKSPACE), { wrapper });

    result.current.download("/chart.png");

    await waitFor(() => expect(result.current.error).toBe("That file could not be downloaded"));
  });
});
