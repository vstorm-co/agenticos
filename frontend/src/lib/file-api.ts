/**
 * File upload API client for chat attachments.
 */

import { apiClient } from "./api-client";
import type { FileAccess } from "./file-access";
import { qk } from "./query-keys";

export interface FileUploadResponse {
  id: string;
  filename: string;
  mime_type: string;
  size: number;
  file_type: string;
  /**
   * The first few lines of the file's extracted text, or null for an image and
   * for anything no parser could read. The composer shows it on the attachment
   * card; the browser cannot derive it, since a PDF is bytes until the backend
   * has parsed it and the client holds only an id once the upload has answered.
   */
  preview: string | null;
}

/**
 * Upload a chat attachment.
 *
 * Through `apiClient.upload` rather than a bare `fetch`: not for the
 * organization header - `/files` is scoped to the user, not the tenant - but
 * for the one-shot 401 refresh and a single `ApiError` shape. This had its own
 * copy of the error handling, which is one copy too many.
 */
export function uploadFile(file: File): Promise<FileUploadResponse> {
  return apiClient.upload<FileUploadResponse>("/files/upload", file);
}

export function getFileUrl(fileId: string): string {
  return `/api/files/${fileId}`;
}

/**
 * The same attachment, addressed through the run whose turn it arrived with.
 *
 * `/files/{id}` is scoped to whoever uploaded it, which is the wrong scope for a
 * run review: reading a run is the organization's right rather than its
 * starter's, so a colleague holding `runs:view` saw the attachment cards on
 * somebody else's transcript and every preview answered 404. The run route
 * authorises through the run - organization, then `runs:view`, then the file has
 * to hang on a turn of that run's own conversation.
 */
export function getRunFileUrl(runId: string, fileId: string): string {
  return `/api/runs/${runId}/files/${fileId}`;
}

/**
 * One chat attachment, as the shared viewer reads it.
 *
 * A same-origin route handler rather than `apiClient`, which is what lets a plain
 * `fetch` work here: `/files` is scoped to the user rather than the tenant, so there
 * is no organization header to lose. The session cookie is the whole of the
 * authorisation, hence `credentials: "include"`.
 *
 * `?disposition=attachment` on the download rather than saving bytes the preview
 * already holds: the route sets the header, and letting the browser follow a link is
 * one fewer copy of the file in memory.
 */
export function attachmentAccess(file: { id: string; filename: string }): FileAccess {
  const url = getFileUrl(file.id);
  const read = async () => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response;
  };

  return {
    textKey: qk.attachments.text(file.id),
    bytesKey: qk.attachments.bytes(file.id),
    readText: async () => ({ content: await (await read()).text(), truncated: false }),
    readBytes: async () => (await read()).blob(),
    download: async () => {
      const link = document.createElement("a");
      link.href = `${url}?disposition=attachment`;
      link.download = file.filename;
      link.click();
    },
  };
}

/**
 * One attachment on a run's transcript, as the shared viewer reads it.
 *
 * `attachmentAccess` with the other address and its own query keys - see
 * `getRunFileUrl` for why there are two. Kept beside it rather than folded into
 * one function taking an optional run: how a surface *reaches* the bytes is a
 * `FileAccess` the caller builds, precisely so the viewer never branches on
 * which authorisation answered.
 */
export function runAttachmentAccess(
  runId: string,
  file: { id: string; filename: string },
): FileAccess {
  const url = getRunFileUrl(runId, file.id);
  const read = async () => {
    const response = await fetch(url, { credentials: "include" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response;
  };

  return {
    textKey: qk.attachments.runText(runId, file.id),
    bytesKey: qk.attachments.runBytes(runId, file.id),
    readText: async () => ({ content: await (await read()).text(), truncated: false }),
    readBytes: async () => (await read()).blob(),
    download: async () => {
      const link = document.createElement("a");
      link.href = `${url}?disposition=attachment`;
      link.download = file.filename;
      link.click();
    },
  };
}
