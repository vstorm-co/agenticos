import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./api-client";
import { postWithProgress } from "./upload-with-progress";

/** An XMLHttpRequest that answers as the test says, and records what it was sent. */
class FakeXhr {
  static last: FakeXhr | null = null;
  status = 0;
  responseText = "";
  withCredentials = false;
  headers: Record<string, string> = {};
  opened: [string, string] | null = null;
  sent: unknown = null;
  upload: {
    onprogress: ((event: ProgressEvent) => void) | null;
    onload: (() => void) | null;
  } = { onprogress: null, onload: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.opened = [method, url];
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.sent = body;
  }
  answer(status: number, body: string) {
    this.status = status;
    this.responseText = body;
    this.onload?.();
  }
}

afterEach(() => vi.unstubAllGlobals());

function start(organizationId: string | null = "org-1") {
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  const onPercent = vi.fn();
  const form = new FormData();
  const done = postWithProgress("/projects/p-1/files", form, {
    organizationId,
    onPercent,
    failed: "Upload failed",
  });
  return { xhr: FakeXhr.last!, onPercent, form, done };
}

describe("postWithProgress", () => {
  it("posts through the BFF in the organization, reporting how much has gone", async () => {
    const { xhr, onPercent, form, done } = start();

    expect(xhr.opened).toEqual(["POST", "/api/projects/p-1/files"]);
    expect(xhr.withCredentials).toBe(true);
    expect(xhr.headers["X-Organization-Id"]).toBe("org-1");
    expect(xhr.sent).toBe(form);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 4 } as ProgressEvent);
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 0, total: 0 } as ProgressEvent);
    xhr.upload.onload?.();
    xhr.answer(201, JSON.stringify({ path: "a.md" }));

    await expect(done).resolves.toEqual({ path: "a.md" });
    expect(onPercent.mock.calls).toEqual([[25], [null], [100]]);
  });

  it("sends no organization header outside one, and takes an empty answer", async () => {
    const { xhr, done } = start(null);
    expect(xhr.headers).toEqual({});
    xhr.answer(204, "");
    await expect(done).resolves.toBeNull();
  });

  it("rejects with the server's own message, or the fallback where there is none", async () => {
    const refused = start();
    refused.xhr.answer(413, JSON.stringify({ error: { message: "Too large" } }));
    await expect(refused.done).rejects.toEqual(expect.objectContaining({ message: "Too large" }));

    const offline = start();
    offline.xhr.onerror?.();
    const error = await offline.done.catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe("Upload failed");
  });
});
