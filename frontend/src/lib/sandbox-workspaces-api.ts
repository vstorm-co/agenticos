/**
 * API client for every workspace this organization's agents keep.
 *
 * The organization-wide sibling of the two routes on a conversation, and it exists
 * because two of the four scopes have no conversation to be addressed through: a
 * `run` workspace never had one, and an `agent` one belongs to every conversation
 * the agent ever answered.
 *
 * The listing carries no files on purpose - a deployment can hold one per warm
 * conversation, so reading each to render a table would be a round trip per row
 * for a page nobody has asked a question of yet.
 */

import { apiClient } from "./api-client";

export interface WorkspaceSummary {
  id: string;
  agent_id: string;
  /** Resolved server-side, so a row names something readable rather than a UUID. */
  agent_name: string;
  conversation_id: string | null;
  /** The chat these files belong to, named. Null when no single conversation owns it. */
  conversation_title: string | null;
  /** How many conversations reach these files. Zero for a run-scoped workspace. */
  conversations: number;
  scope: string;
  backend: string;
  /** Whose workspace this is, in words. Under `agent` scope this is the whole point. */
  owner_label: string;
  /** Who can see the files. `scope` is the mechanism; this is the consequence. */
  access_label: string;
  bytes_total: number;
  version: number;
  last_used_at: string | null;
  created_at: string | null;
}

interface WorkspaceSummaryList {
  items: WorkspaceSummary[];
  total: number;
}

export interface WorkspaceFile {
  path: string;
  size: number | null;
  is_dir: boolean;
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
}

/** One file in the flat view, with the workspace it came from named beside it. */
export interface FlatFile extends WorkspaceFile {
  workspace_id: string;
  agent_name: string;
  access_label: string;
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

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  const data = await apiClient.get<WorkspaceSummaryList>(ROOT);
  return data.items;
}

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
