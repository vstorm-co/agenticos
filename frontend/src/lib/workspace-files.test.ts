import { describe, expect, it, vi } from "vitest";

import { bytesKey, readFileBytes, readFileText, textKey } from "./workspace-files";
import { apiClient } from "./api-client";

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
