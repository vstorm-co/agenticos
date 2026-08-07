import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useFileActions, useFileBytes, useFileText } from "./use-file-content";
import * as conversationApi from "@/lib/conversation-workspace-api";
import * as workspaceApi from "@/lib/sandbox-workspaces-api";
import { workspaceFileAccess, type FileSource } from "@/lib/workspace-files";

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

/** Anchors on a real `FileAccess` rather than a stub, so the two halves stay honest. */
const chatFile = (path = "/a.txt") => workspaceFileAccess(IN_CHAT, path);
const workspaceFile = (path = "/a.txt") => workspaceFileAccess(IN_WORKSPACE, path);

/** An anchor whose click is observable, which jsdom's is not. */
function captureAnchors(): HTMLAnchorElement[] {
  const clicked: HTMLAnchorElement[] = [];
  const create = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
    const element = create(tag) as HTMLAnchorElement;
    if (tag === "a") element.click = () => clicked.push(element);
    return element;
  });
  return clicked;
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.clearAllMocks();
  Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
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
 * chat was shared with. The hooks take a `FileAccess` and never learn which, so the
 * viewer above them cannot end up with a different set of behaviours per surface.
 */
describe("one file's text", () => {
  it("reads a chat's file through its conversation", async () => {
    const { result } = renderHook(() => useFileText(chatFile()), { wrapper });

    await waitFor(() => expect(result.current.file?.content).toBe("hello"));
    expect(conversationApi.readConversationFile).toHaveBeenCalledWith("c-1", "/a.txt");
    expect(workspaceApi.readWorkspaceFile).not.toHaveBeenCalled();
  });

  it("reads a workspace's file through its id", async () => {
    const { result } = renderHook(() => useFileText(workspaceFile()), { wrapper });

    await waitFor(() => expect(result.current.file?.content).toBe("hello"));
    expect(workspaceApi.readWorkspaceFile).toHaveBeenCalledWith("w-1", "/a.txt");
  });

  it("reports one that could not be read", async () => {
    vi.mocked(workspaceApi.readWorkspaceFile).mockRejectedValue(new Error("404 Not Found"));
    const { result } = renderHook(() => useFileText(workspaceFile()), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("404 Not Found"));
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(workspaceApi.readWorkspaceFile).mockRejectedValue("nope");
    const { result } = renderHook(() => useFileText(workspaceFile()), { wrapper });

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
    const { result } = renderHook(() => useFileBytes(workspaceFile("/chart.png")), { wrapper });

    await waitFor(() => expect(result.current.url).toBe("blob:0"));
    expect(workspaceApi.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/chart.png", {});
  });

  it("says what the server called it, so a viewer does not guess from the suffix", async () => {
    // The API decides what may be shown inline. A client list of suffixes deciding it
    // too is a second answer, and when the two disagreed an `<img>` got a blob typed
    // `application/octet-stream` and showed a broken image with nothing saying why.
    const { result } = renderHook(() => useFileBytes(chatFile("/report.pdf")), { wrapper });

    await waitFor(() => expect(result.current.mediaType).toBe("application/pdf"));
  });

  it("releases the URL when it is done with it", async () => {
    // A blob URL holds the bytes alive until it is revoked, and a PDF or a chart adds
    // up over a session of clicking through files.
    const { result, unmount } = renderHook(() => useFileBytes(workspaceFile("/chart.png")), {
      wrapper,
    });
    await waitFor(() => expect(result.current.url).toBe("blob:0"));

    unmount();

    expect(revoked).toEqual(["blob:0"]);
  });

  it("reports a refusal rather than a blank preview", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(
      new Error("This host can only read text"),
    );

    const { result } = renderHook(() => useFileBytes(workspaceFile("/chart.png")), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("This host can only read text"));
    expect(result.current.url).toBeNull();
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue("nope");
    const { result } = renderHook(() => useFileBytes(workspaceFile("/chart.png")), { wrapper });

    await waitFor(() => expect(result.current.error).toBe("That file could not be read"));
  });

  it("keys text apart from bytes, so one cannot be served as the other", async () => {
    const access = workspaceFile("/report.pdf");

    expect(access.bytesKey).not.toEqual(access.textKey);
  });
});

describe("saving a file to disk", () => {
  it("asks for it as a download and names it after the file", async () => {
    // `download=true` and not the bytes a preview already holds: that is what makes
    // the server answer `attachment`, and for everything off its short inline list it
    // is the only way the bytes come back at all.
    const clicked = captureAnchors();
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));

    await workspaceFile("/out/report.csv").download();

    expect(workspaceApi.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/out/report.csv", {
      download: true,
    });
    expect(clicked[0]?.download).toBe("report.csv");
  });

  it("saves a chat's file through the conversation route", async () => {
    captureAnchors();
    vi.mocked(conversationApi.readConversationFileBytes).mockResolvedValue(new Blob(["%PDF-"]));

    await chatFile("/report.pdf").download();

    expect(conversationApi.readConversationFileBytes).toHaveBeenCalledWith("c-1", "/report.pdf", {
      download: true,
    });
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
    captureAnchors();
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));

    await workspaceFile("/report.csv").download();

    expect(revoked).not.toContain("blob:deferred");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(revoked).toContain("blob:deferred");
  });

  it("falls back to a name when the path ends in a slash", async () => {
    const clicked = captureAnchors();
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob([""]));

    await workspaceFile("/").download();

    expect(clicked[0]?.download).toBe("file");
  });
});

describe("the two things done to a file besides looking at it", () => {
  it("says why a download was refused, rather than looking like a dead button", async () => {
    // The certain case: a binary in a container-backed workspace is read through an
    // archive that can only read text, so the API answers 400. A bare `void
    // access.download()` dropped that on the floor.
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(
      new Error("This host can only read text"),
    );
    const { result } = renderHook(() => useFileActions(workspaceFile("/chart.png")), { wrapper });

    result.current.download();

    await waitFor(() => expect(result.current.error).toBe("This host can only read text"));
  });

  it("clears the last refusal when a new attempt starts", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(new Error("nope"));
    captureAnchors();
    const { result } = renderHook(() => useFileActions(workspaceFile("/chart.png")), { wrapper });
    result.current.download();
    await waitFor(() => expect(result.current.error).toBe("nope"));
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["a,b"]));

    result.current.download();

    await waitFor(() => expect(result.current.error).toBeNull());
  });

  it("falls back to a sentence when the failure is not an Error", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue("nope");
    const { result } = renderHook(() => useFileActions(workspaceFile("/chart.png")), { wrapper });

    result.current.download();

    await waitFor(() => expect(result.current.error).toBe("That file could not be fetched"));
  });

  it("opens a tab on the bytes it fetched, not on the API's URL", async () => {
    // The bytes are fetched with the organization header this page is scoped to, so
    // the tab shows the same tenant's file. A bare URL would arrive without it and be
    // answered for the caller's personal organization instead.
    const open = vi.fn();
    vi.stubGlobal("open", open);
    vi.mocked(workspaceApi.readWorkspaceBytes).mockResolvedValue(new Blob(["%PDF-"]));
    const { result } = renderHook(() => useFileActions(workspaceFile("/report.pdf")), { wrapper });

    result.current.openInNewTab();

    await waitFor(() =>
      expect(open).toHaveBeenCalledWith("blob:x", "_blank", "noopener,noreferrer"),
    );
    expect(workspaceApi.readWorkspaceBytes).toHaveBeenCalledWith("w-1", "/report.pdf", {});
    vi.unstubAllGlobals();
  });

  it("reports a tab it could not open", async () => {
    vi.mocked(workspaceApi.readWorkspaceBytes).mockRejectedValue(new Error("gone"));
    const { result } = renderHook(() => useFileActions(workspaceFile("/report.pdf")), { wrapper });

    result.current.openInNewTab();

    await waitFor(() => expect(result.current.error).toBe("gone"));
  });
});
