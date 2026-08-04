import { describe, expect, it, vi } from "vitest";

import {
  bytesKey,
  isMarkdown,
  isTextual,
  readFileBytes,
  readFileText,
  suffixOf,
  textKey,
} from "./workspace-files";
import { apiClient } from "./api-client";

vi.mock("./api-client", () => ({
  apiClient: { get: vi.fn().mockResolvedValue({}), raw: vi.fn().mockResolvedValue(new Response()) },
}));

describe("reading a path", () => {
  it("takes the suffix off the name, not off the folders", () => {
    expect(suffixOf("/skills/code-review/SKILL.md")).toBe("md");
  });

  it("has no suffix for a file with none", () => {
    expect(suffixOf("/Makefile")).toBe("");
    expect(suffixOf("/.env")).toBe("");
  });

  it("lowercases it, because a listing does not", () => {
    expect(suffixOf("/CHART.PNG")).toBe("png");
  });
});

/**
 * Which request a file gets, which is the only thing a suffix decides here.
 *
 * Whether the answer can be *shown* is the server's call, read off the response type -
 * so `.svg` asks for its text like any other text file, and it is the API refusing to
 * serve one inline that keeps it off the screen.
 */
describe("choosing text or bytes", () => {
  it("asks for text for what can be read as a string", () => {
    expect(isTextual("/report.csv")).toBe(true);
    expect(isTextual("/notes.md")).toBe(true);
    expect(isTextual("/logo.svg")).toBe(true);
  });

  it("asks for bytes for a picture, a PDF and anything it does not know", () => {
    expect(isTextual("/chart.png")).toBe(false);
    expect(isTextual("/report.pdf")).toBe(false);
    expect(isTextual("/Makefile")).toBe(false);
  });

  it("offers a rendered view only for markdown", () => {
    expect(isMarkdown("/notes.md")).toBe(true);
    expect(isMarkdown("/notes.markdown")).toBe(true);
    expect(isMarkdown("/notes.txt")).toBe(false);
  });
});

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
