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
  scope: string;
  backend: string;
  /** Whose workspace this is, in words. Under `agent` scope this is the whole point. */
  owner_label: string;
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
