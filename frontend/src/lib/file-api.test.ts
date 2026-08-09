import { afterEach, describe, expect, it, vi } from "vitest";

import { attachmentAccess, getFileUrl, uploadFile } from "./file-api";
import { ApiError } from "./api-client";

/**
 * Chat attachments, which go through this app's own route rather than to the
 * platform: the browser has a session cookie and no bearer token, and the file
 * is read back through the same route for the same reason.
 */
describe("uploadFile", () => {
  afterEach(() => vi.unstubAllGlobals());

  /** A stubbed response, with `text` derived from `json` as the client reads it. */
  function respond(response: Partial<Response> & { json: () => Promise<unknown> }) {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: () => response.json().then((body) => JSON.stringify(body)),
      ...response,
    });
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

    await expect(uploadFile(new File(["x"], "a.pdf"))).rejects.toThrow("Request failed");
  });

  it("still fails loudly when the refusal names no reason", async () => {
    respond({ ok: false, status: 500, json: () => Promise.resolve({}) });

    await expect(uploadFile(new File(["x"], "a.pdf"))).rejects.toThrow("Request failed");
  });
});

describe("getFileUrl", () => {
  it("addresses a stored file through this app, not the platform", () => {
    expect(getFileUrl("f-1")).toBe("/api/files/f-1");
  });
});

/**
 * One attachment, as the shared viewer reads it.
 *
 * A plain `fetch` and not `apiClient`, which is the one thing about this origin worth
 * asserting: `/files` is scoped to the user rather than the tenant, so there is no
 * organization header to lose and the session cookie is the whole authorisation.
 */
describe("attachmentAccess", () => {
  afterEach(() => vi.unstubAllGlobals());

  function serve(response: Partial<Response>) {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, ...response });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  const file = { id: "f-1", filename: "invoice.pdf" };

  it("sends the session cookie, because the file is behind it", async () => {
    const fetchMock = serve({ text: () => Promise.resolve("hello") });

    await attachmentAccess(file).readText();

    expect(fetchMock).toHaveBeenCalledWith("/api/files/f-1", { credentials: "include" });
  });

  it("answers text as the shape every origin answers", async () => {
    serve({ text: () => Promise.resolve("hello") });

    expect(await attachmentAccess(file).readText()).toEqual({
      content: "hello",
      truncated: false,
    });
  });

  it("answers bytes for what is rendered from them", async () => {
    const blob = new Blob(["%PDF-"], { type: "application/pdf" });
    serve({ blob: () => Promise.resolve(blob) });

    expect(await attachmentAccess(file).readBytes()).toBe(blob);
  });

  it("says a file could not be fetched rather than rendering empty", async () => {
    // The panel is opened from a message; the file behind it can have been deleted,
    // or belong to a conversation somebody lost access to.
    serve({ ok: false, status: 404 });

    await expect(attachmentAccess(file).readText()).rejects.toThrow("HTTP 404");
  });

  it("asks the route for an attachment rather than saving bytes it already has", async () => {
    // The route sets the header, and letting the browser follow a link is one fewer
    // copy of the file in memory.
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await attachmentAccess(file).download();

    const anchor = click.mock.instances[0] as HTMLAnchorElement;
    expect(anchor.getAttribute("href")).toBe("/api/files/f-1?disposition=attachment");
    expect(anchor.download).toBe("invoice.pdf");
    click.mockRestore();
  });

  it("keys its two bodies apart, because one route answers both", () => {
    const access = attachmentAccess(file);

    expect(access.textKey).not.toEqual(access.bytesKey);
  });
});
