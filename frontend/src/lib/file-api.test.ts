import { afterEach, describe, expect, it, vi } from "vitest";

import { getFileUrl, uploadFile } from "./file-api";
import { ApiError } from "./api-client";

/**
 * Chat attachments, which go through this app's own route rather than to the
 * platform: the browser has a session cookie and no bearer token, and the file
 * is read back through the same route for the same reason.
 */
describe("uploadFile", () => {
  afterEach(() => vi.unstubAllGlobals());

  function respond(response: Partial<Response> & { json: () => Promise<unknown> }) {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("posts the file as multipart, which is the only shape the route takes", async () => {
    const fetchMock = respond({ json: () => Promise.resolve({ id: "f-1", filename: "a.pdf" }) });

    const uploaded = await uploadFile(new File(["x"], "a.pdf", { type: "application/pdf" }));

    expect(uploaded).toMatchObject({ id: "f-1" });
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/files/upload");
    expect(init.method).toBe("POST");
    expect((init.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("raises the server's own refusal, with its status", async () => {
    // The chat shows this sentence; "Upload failed" would hide "file too large".
    respond({
      ok: false,
      status: 413,
      json: () => Promise.resolve({ detail: "File exceeds 50 MB" }),
    });

    await expect(uploadFile(new File(["x"], "big.pdf"))).rejects.toThrow("File exceeds 50 MB");
    await expect(uploadFile(new File(["x"], "big.pdf"))).rejects.toBeInstanceOf(ApiError);
  });

  it("still fails loudly when the refusal is not JSON", async () => {
    // A proxy timeout answers with HTML, and `.json()` rejects.
    respond({ ok: false, status: 502, json: () => Promise.reject(new Error("not json")) });

    await expect(uploadFile(new File(["x"], "a.pdf"))).rejects.toThrow("Upload failed");
  });

  it("still fails loudly when the refusal names no reason", async () => {
    respond({ ok: false, status: 500, json: () => Promise.resolve({}) });

    await expect(uploadFile(new File(["x"], "a.pdf"))).rejects.toThrow("Upload failed");
  });
});

describe("getFileUrl", () => {
  it("addresses a stored file through this app, not the platform", () => {
    expect(getFileUrl("f-1")).toBe("/api/files/f-1");
  });
});
