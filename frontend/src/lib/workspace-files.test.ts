import { describe, expect, it, vi } from "vitest";

import {
  bytesKey,
  documentName,
  downloadConversationFolder,
  readFileBytes,
  readFileText,
  textKey,
  workspaceFileAccess,
} from "./workspace-files";
import { apiClient } from "./api-client";
import { readLocalFile } from "./desktop/commands";

vi.mock("./desktop/commands", () => ({ readLocalFile: vi.fn() }));

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue({}), raw: vi.fn().mockResolvedValue(new Response()) },
}));

/**
 * The two addresses one file can have.
 *
 * A conversation authorises by being fetched, which somebody a chat was shared with
 * passes; a workspace id is checked against the rows that caller may see. The same
 * viewer uses both, so the routes have to stay distinct here rather than in it.
 */
describe("addressing a file", () => {
  it("reads a conversation's file through the conversation", async () => {
    await readFileText({ kind: "conversation", id: "c1" }, "/out/report.csv");

    expect(vi.mocked(apiClient.get).mock.calls[0]?.[0]).toBe(
      "/conversations/c1/workspace/file?path=%2Fout%2Freport.csv",
    );
  });

  it("reads a workspace's file through its id", async () => {
    await readFileText({ kind: "workspace", id: "w1" }, "/out/report.csv");

    expect(vi.mocked(apiClient.get).mock.calls.at(-1)?.[0]).toBe(
      "/sandbox-workspaces/w1/file?path=%2Fout%2Freport.csv",
    );
  });

  it("asks a conversation for bytes, and for a download when that is what it is", async () => {
    await readFileBytes({ kind: "conversation", id: "c1" }, "/chart.png", { download: true });

    expect(vi.mocked(apiClient.raw).mock.calls.at(-1)?.[0]).toBe(
      "/conversations/c1/workspace/raw?path=%2Fchart.png&download=true",
    );
  });

  it("reads a project's file through the project, text decoded from its bytes", async () => {
    vi.mocked(apiClient.raw).mockImplementation(async () => new Response("# Brief"));
    await expect(readFileText({ kind: "project", id: "p1" }, "brief.md")).resolves.toEqual({
      content: "# Brief",
      truncated: false,
    });
    await readFileBytes({ kind: "project", id: "p1" }, "a.png", { download: true });
    expect(vi.mocked(apiClient.raw).mock.calls.at(-1)?.[0]).toBe(
      "/projects/p1/files/raw?path=a.png&download=true",
    );
    expect(textKey({ kind: "project", id: "p1" }, "a")).not.toEqual(
      textKey({ kind: "workspace", id: "p1" }, "a"),
    );
    expect(bytesKey({ kind: "project", id: "p1" }, "a")).not.toEqual(
      bytesKey({ kind: "workspace", id: "p1" }, "a"),
    );
  });

  it("keys the two addresses apart, so one cache entry cannot answer for the other", () => {
    expect(textKey({ kind: "conversation", id: "x" }, "/a")).not.toEqual(
      textKey({ kind: "workspace", id: "x" }, "/a"),
    );
    // And text is keyed apart from bytes: two different bodies for one path.
    expect(bytesKey({ kind: "conversation", id: "x" }, "/a")).not.toEqual(
      textKey({ kind: "conversation", id: "x" }, "/a"),
    );
  });
});

describe("documentName - a file as a person calls it", () => {
  it("drops the folders and an attachment's filing prefix", () => {
    expect(documentName("/uploads/0d7d5756-handbook.pdf", true)).toBe("handbook.pdf");
  });

  it("keeps an agent's own name whole, prefix-like or not", () => {
    expect(documentName("/reports/0d7d5756-q3.csv", false)).toBe("0d7d5756-q3.csv");
    expect(documentName("notes.md", false)).toBe("notes.md");
  });

  it("keeps a name that is nothing but the prefix", () => {
    expect(documentName("/uploads/0d7d5756-", true)).toBe("0d7d5756-");
  });
});

describe("native file source", () => {
  it("reads only the selected root through IPC and bounds text previews", async () => {
    const source = { kind: "local", root: "/approved" } as const;
    vi.mocked(readLocalFile).mockResolvedValue(new TextEncoder().encode("hello"));
    await expect(readFileText(source, "a.txt")).resolves.toEqual({
      content: "hello",
      truncated: false,
    });
    expect(readLocalFile).toHaveBeenLastCalledWith("/approved", "a.txt");
    vi.mocked(readLocalFile).mockResolvedValue(new Uint8Array(512 * 1024 + 1).fill(97));
    const text = await readFileText(source, "large.txt");
    expect(text.truncated).toBe(true);
    expect(text.content).toHaveLength(512 * 1024);
    const blob = await readFileBytes(source, "large.txt");
    expect(blob.size).toBe(512 * 1024 + 1);
    expect(textKey(source, "a")).not.toEqual(textKey({ kind: "local", root: "/other" }, "a"));
    expect(bytesKey(source, "a")).not.toEqual(textKey(source, "a"));
  });
});

it("prepares linked local CSS through the same root and leaves Source unchanged", async () => {
  const html = '<link rel="stylesheet" href="style.css"><h1>Hello</h1>';
  vi.mocked(readLocalFile).mockImplementation(async (_root, path) =>
    new TextEncoder().encode(path.endsWith(".css") ? "h1{color:green}" : html),
  );
  const access = workspaceFileAccess({ kind: "local", root: "/approved" }, "site/index.html");
  await expect(access.readPreview?.()).resolves.toMatchObject({
    content: expect.stringContaining("<style>h1{color:green}</style>"),
  });
  expect(readLocalFile).toHaveBeenCalledWith("/approved", "site/style.css");
  await expect(access.readText()).resolves.toEqual({ content: html, truncated: false });
});

it("loads CSS image bytes through the original local root", async () => {
  const html = '<link rel="stylesheet" href="style.css">';
  vi.mocked(readLocalFile).mockImplementation(async (_root, path) =>
    new TextEncoder().encode(
      path.endsWith(".css")
        ? 'body{background:url("image.png")}'
        : path.endsWith(".png")
          ? "image-bytes"
          : html,
    ),
  );
  const preview = await workspaceFileAccess(
    { kind: "local", root: "/original" },
    "site/index.html",
  ).readPreview?.();
  expect(preview?.content).toContain("data:image/png;base64,");
  expect(readLocalFile).toHaveBeenCalledWith("/original", "site/image.png");
});

/**
 * A folder out as one `.zip` (#2479): through the conversation, as one file is, and
 * saved under the folder's own name - or `workspace.zip` for the whole of it.
 */
describe("downloading a folder", () => {
  it.each([
    ["uploads/3f2a1b9c-repo", "uploads%2F3f2a1b9c-repo", "3f2a1b9c-repo.zip"],
    ["/out/", "%2Fout%2F", "out.zip"],
    ["", "", "workspace.zip"],
    [".", ".", "workspace.zip"],
  ])("asks the archive route for %j and saves it as %s", async (folder, encoded, saved) => {
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      names.push(this.download);
    });
    Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
    vi.mocked(apiClient.raw).mockResolvedValueOnce({
      blob: async () => new Blob(["PK"]),
    } as unknown as Response);

    await downloadConversationFolder("c1", folder);

    expect(vi.mocked(apiClient.raw).mock.calls.at(-1)?.[0]).toBe(
      `/conversations/c1/workspace/archive?path=${encoded}`,
    );
    expect(names).toEqual([saved]);
    click.mockRestore();
  });
});
