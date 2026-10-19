/**
 * API client for every workspace this organization's agents keep.
 *
 * The organization-wide sibling of the two routes on a conversation, and it exists
 * because two of the four scopes have no conversation to be addressed through: a
 * `run` workspace never had one, and an `agent` one belongs to every conversation
 * the agent ever answered.
 *
 * The console reads every file at once for the Documents page, and one
 * workspace's files for the folder a file sits in.
 */

import { apiClient } from "./api-client";

export interface WorkspaceFile {
  path: string;
  size: number | null;
  is_dir: boolean;
  /** ISO 8601, or null where the backend records no per-file time. */
  modified_at: string | null;
}

export interface WorkspaceFiles {
  scope: string;
  backend: string;
  owner_label: string;
  items: WorkspaceFile[];
  total: number;
  bytes_total: number;
  /**
   * Why the listing may be empty despite the workspace holding files.
   *
   * A configuration rather than a fault, most of the time: a service started with
   * no `workspace_root` keeps nothing on disk, so its files exist only while a
   * sandbox runs. Shown as an explanation, not as a red error.
   */
  unreadable_reason: string | null;
  /**
   * Whether the host answered and this is still not all of it.
   *
   * Reading a container's files is a round trip per directory, so the walk stops
   * at six levels and 2,000 entries - which for a workspace holding a checkout is
   * a tree a person would otherwise read as complete.
   */
  truncated: boolean;
}

/** One file in the flat view, with the workspace it came from named beside it. */
export interface FlatFile extends WorkspaceFile {
  workspace_id: string;
  agent_id: string;
  agent_name: string;
  /** The handle the agent's generated face is drawn from; empty once it is deleted. */
  agent_slug: string;
  agent_has_avatar: boolean;
  access_label: string;
  /** The conversation a conversation-scoped workspace belongs to; null otherwise. */
  conversation_title?: string | null;
  /** That conversation, set only when it is the reader's own to open. */
  conversation_id?: string | null;
  /**
   * Whether a person attached this file rather than an agent writing it.
   *
   * Read off the path server-side - attachments land in `uploads/` - because a
   * host records no author. It is what makes "which of these did I give it" a
   * question this list can answer.
   */
  from_upload: boolean;
  /** The first lines of a stored text file; null for binary content and for
   *  container-backed workspaces, whose bytes the flat listing does not fetch. */
  preview: string | null;
  /** A stored image, scaled server-side into a `data:` URI. Null for everything
   *  else - an address per tile would be a request per tile. */
  thumbnail: string | null;
}

/**
 * Every file the caller can see, across their workspaces.
 *
 * `truncated` and `unreadable` are part of the answer rather than diagnostics: a
 * shorter list is indistinguishable from fewer files, and "no agent is holding
 * that document" is a different statement from "we stopped looking".
 */
export interface FlatFileList {
  items: FlatFile[];
  total: number;
  workspaces_read: number;
  unreadable: number;
  truncated: boolean;
}

export interface WorkspaceFileContent {
  path: string;
  content: string;
  truncated: boolean;
}

const ROOT = "/sandbox-workspaces";

/**
 * One file's bytes: a download, or an image a preview can render.
 *
 * Through `apiClient.raw` rather than as an `<img src>`, and that is not a
 * preference. A bare browser request carries no `X-Organization-Id`, so the backend
 * would fall back to the caller's personal organization and serve - or refuse - a
 * file from a different tenant than the one on screen. The caller turns this into a
 * blob URL.
 */
export async function readWorkspaceBytes(
  id: string,
  path: string,
  { download = false }: { download?: boolean } = {},
): Promise<Blob> {
  const response = await apiClient.raw(
    `${ROOT}/${id}/raw?path=${encodeURIComponent(path)}${download ? "&download=true" : ""}`,
  );
  return response.blob();
}

/** Every file at once, for the view that asks "who is holding a copy of this". */
export async function listAllWorkspaceFiles(): Promise<FlatFileList> {
  return apiClient.get<FlatFileList>(`${ROOT}/files`);
}

export async function readWorkspaceFiles(id: string): Promise<WorkspaceFiles> {
  return apiClient.get<WorkspaceFiles>(`${ROOT}/${id}/files`);
}

/**
 * One file's text.
 *
 * The path goes in a query parameter because workspace paths contain slashes, so
 * a path segment would need escaping this client would have to get exactly right.
 */
export async function readWorkspaceFile(id: string, path: string): Promise<WorkspaceFileContent> {
  return apiClient.get<WorkspaceFileContent>(`${ROOT}/${id}/file?path=${encodeURIComponent(path)}`);
}
