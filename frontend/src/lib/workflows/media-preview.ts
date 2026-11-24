import { apiClient } from "@/lib/api-client";
import type { WorkflowRunFile } from "@/lib/workflows/types";

/** A preview is an explicit, bounded read; larger files keep their download action. */
export const WORKFLOW_MEDIA_PREVIEW_BYTES = 64 * 1024 * 1024;

const MEDIA_TYPES = new Set([
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
]);

type PreviewFile = Pick<WorkflowRunFile, "id" | "content_type" | "byte_size">;

export function isWorkflowMediaFile(file: PreviewFile): boolean {
  return MEDIA_TYPES.has(file.content_type);
}

export function canPreviewWorkflowMedia(file: PreviewFile): boolean {
  return (
    isWorkflowMediaFile(file) &&
    Number.isSafeInteger(file.byte_size) &&
    file.byte_size > 0 &&
    file.byte_size <= WORKFLOW_MEDIA_PREVIEW_BYTES
  );
}

/**
 * Only the existing authorized run-file route supplies bytes. The recorded type
 * and size must match the response; SVG, HTML and provider URLs never enter the
 * shared viewer. The stream limit still applies when Content-Length is absent.
 */
export async function readWorkflowMediaPreview(
  runId: string,
  file: PreviewFile,
  signal?: AbortSignal,
): Promise<Blob> {
  if (!canPreviewWorkflowMedia(file)) throw new Error();
  signal?.throwIfAborted();
  const response = await apiClient.raw(
    `/workflow-runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(file.id)}`,
    { signal, cache: "no-store" },
  );
  const type = response.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase();
  const length = response.headers.get("content-length");
  if (
    type !== file.content_type ||
    (length !== null && (!/^\d+$/.test(length) || Number(length) > file.byte_size)) ||
    response.body === null
  ) {
    await response.body?.cancel();
    throw new Error();
  }
  const reader = response.body.getReader();
  const chunks: ArrayBuffer[] = [];
  let bytes = 0;
  let finished = false;
  try {
    for (;;) {
      signal?.throwIfAborted();
      const next = await reader.read();
      if (next.done) {
        finished = true;
        break;
      }
      bytes += next.value.byteLength;
      if (bytes > file.byte_size) throw new Error();
      chunks.push(new Uint8Array(next.value).buffer);
    }
  } finally {
    try {
      if (!finished) await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
  signal?.throwIfAborted();
  if (bytes !== file.byte_size) throw new Error();
  return new Blob(chunks, { type: file.content_type });
}
