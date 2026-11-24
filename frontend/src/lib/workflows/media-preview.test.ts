import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";

import {
  canPreviewWorkflowMedia,
  isWorkflowMediaFile,
  readWorkflowMediaPreview,
  WORKFLOW_MEDIA_PREVIEW_BYTES,
} from "./media-preview";

vi.mock("@/lib/api-client", () => ({ apiClient: { raw: vi.fn() } }));

const FILE = { id: "file/id", content_type: "image/png", byte_size: 4 };

function response(
  chunks: number[][] = [
    [1, 2],
    [3, 4],
  ],
  headers: Record<string, string> = { "content-type": "image/png" },
) {
  const cancel = vi.fn();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new Uint8Array(chunk));
      controller.close();
    },
    cancel,
  });
  const value = new Response(stream, { headers });
  vi.mocked(apiClient.raw).mockResolvedValue(value);
  return { value, cancel };
}

beforeEach(() => vi.resetAllMocks());

describe("bounded workflow media preview", () => {
  it.each([
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/mpeg",
    "audio/ogg",
    "audio/webm",
    "audio/mp4",
    "video/mp4",
    "video/webm",
  ])("allows the recorded raster, audio or video type %s", (content_type) => {
    expect(canPreviewWorkflowMedia({ ...FILE, content_type })).toBe(true);
  });

  it.each(["image/svg+xml", "text/html", "application/pdf", "application/octet-stream", ""])(
    "refuses active or unsupported content %s before requesting bytes",
    async (content_type) => {
      const file = { ...FILE, content_type };
      expect(isWorkflowMediaFile(file)).toBe(false);
      await expect(readWorkflowMediaPreview("run", file)).rejects.toThrow();
      expect(apiClient.raw).not.toHaveBeenCalled();
    },
  );

  it.each([0, -1, 0.5, Number.NaN, Number.POSITIVE_INFINITY, WORKFLOW_MEDIA_PREVIEW_BYTES + 1])(
    "refuses an invalid or excessive recorded size %s before requesting bytes",
    async (byte_size) => {
      await expect(readWorkflowMediaPreview("run", { ...FILE, byte_size })).rejects.toThrow();
      expect(apiClient.raw).not.toHaveBeenCalled();
    },
  );

  it("admits exactly the documented limit", () => {
    expect(canPreviewWorkflowMedia({ ...FILE, byte_size: WORKFLOW_MEDIA_PREVIEW_BYTES })).toBe(
      true,
    );
  });

  it("reads the encoded authorized route without caching and keeps the recorded media type", async () => {
    response(
      [
        [1, 2],
        [3, 4],
      ],
      { "content-type": "Image/PNG; charset=binary", "content-length": "4" },
    );
    const controller = new AbortController();
    const blob = await readWorkflowMediaPreview("run/id", FILE, controller.signal);
    expect(apiClient.raw).toHaveBeenCalledWith("/workflow-runs/run%2Fid/files/file%2Fid", {
      signal: controller.signal,
      cache: "no-store",
    });
    expect(blob.size).toBe(4);
    expect(blob.type).toBe("image/png");
  });

  it("enforces the stream bound when a response omits Content-Length", async () => {
    response();
    expect((await readWorkflowMediaPreview("run", FILE)).size).toBe(4);
    const oversized = response([[1, 2, 3], [4, 5], [6]]);
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow();
    expect(oversized.cancel).toHaveBeenCalledTimes(1);
    expect(oversized.value.body?.locked).toBe(false);
  });

  it.each<Record<string, string>>([
    {},
    { "content-type": "text/html" },
    { "content-type": "image/png", "content-length": "five" },
    { "content-type": "image/png", "content-length": "-4" },
    { "content-type": "image/png", "content-length": "4.0" },
    { "content-type": "image/png", "content-length": "5" },
  ])("cancels a response whose headers do not match the file %j", async (headers) => {
    const { cancel } = response([[1, 2, 3, 4]], headers);
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow();
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("refuses a response without a body", async () => {
    vi.mocked(apiClient.raw).mockResolvedValue(
      new Response(null, { headers: { "content-type": "image/png" } }),
    );
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow();
  });

  it.each([{ chunks: [] }, { chunks: [[1, 2, 3]] }])(
    "refuses an empty or truncated body $chunks",
    async ({ chunks }) => {
      const { value } = response(chunks);
      await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow();
      expect(value.body?.locked).toBe(false);
    },
  );

  it("does not start a request after its viewer has already closed", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(readWorkflowMediaPreview("run", FILE, controller.signal)).rejects.toThrow();
    expect(apiClient.raw).not.toHaveBeenCalled();
  });

  it("discards bytes and releases the reader if cancellation arrives during a read", async () => {
    const controller = new AbortController();
    const value = new Response(
      new ReadableStream<Uint8Array>({
        pull(stream) {
          controller.abort();
          stream.enqueue(new Uint8Array([1, 2, 3, 4]));
        },
      }),
      { headers: { "content-type": "image/png" } },
    );
    vi.mocked(apiClient.raw).mockResolvedValue(value);
    await expect(readWorkflowMediaPreview("run", FILE, controller.signal)).rejects.toThrow();
    expect(value.body?.locked).toBe(false);
  });

  it("does not return a completed body if cancellation wins the final read", async () => {
    const controller = new AbortController();
    const value = new Response(
      new ReadableStream<Uint8Array>({
        start(stream) {
          stream.enqueue(new Uint8Array([1, 2, 3, 4]));
        },
        pull(stream) {
          controller.abort();
          stream.close();
        },
      }),
      { headers: { "content-type": "image/png" } },
    );
    vi.mocked(apiClient.raw).mockResolvedValue(value);
    await expect(readWorkflowMediaPreview("run", FILE, controller.signal)).rejects.toThrow();
    expect(value.body?.locked).toBe(false);
  });

  it("releases the stream lock even when cancellation itself fails", async () => {
    const value = new Response(
      new ReadableStream<Uint8Array>({
        start(stream) {
          stream.enqueue(new Uint8Array([1, 2, 3, 4, 5]));
        },
        cancel() {
          throw new Error("cancel failed");
        },
      }),
      { headers: { "content-type": "image/png" } },
    );
    vi.mocked(apiClient.raw).mockResolvedValue(value);
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow("cancel failed");
    expect(value.body?.locked).toBe(false);
  });

  it("releases an errored stream and preserves the failure", async () => {
    const value = new Response(
      new ReadableStream<Uint8Array>({
        start(stream) {
          stream.error(new Error("stream failed"));
        },
      }),
      { headers: { "content-type": "image/png" } },
    );
    vi.mocked(apiClient.raw).mockResolvedValue(value);
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow("stream failed");
    expect(value.body?.locked).toBe(false);
  });

  it("preserves an authorization failure without retrying", async () => {
    vi.mocked(apiClient.raw).mockRejectedValue(new Error("refused"));
    await expect(readWorkflowMediaPreview("run", FILE)).rejects.toThrow("refused");
    expect(apiClient.raw).toHaveBeenCalledTimes(1);
  });
});
