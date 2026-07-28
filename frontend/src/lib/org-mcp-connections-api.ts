/**
 * API client for the organization's MCP servers.
 *
 * The sibling of `mcp-connections-api.ts`, and the difference between them is
 * the difference the whole feature turns on. That one talks to
 * `/me/mcp-connections`: a person's own servers, their own credentials, only
 * their own assistant. This one talks to `/mcp-connections`: servers the
 * organization owns, gated on `connections:manage`, and the only ones an agent
 * can be built on - a published agent that reached different tools depending on
 * who ran it would be neither reviewable nor reproducible.
 *
 * The credential is write-only here as it is there: it goes in, it is sealed
 * for the organization, and no response ever carries it back.
 */

import { apiClient } from "./api-client";
import type { McpConnectionRecord, McpConnectionTestResult } from "./mcp-connections-api";

/**
 * One organization server.
 *
 * Adds `catalog_key` to the personal shape: the backend records which curated
 * entry a server came from, so the Builder can show a real name instead of
 * guessing one from the URL. Null for a server added by raw URL.
 *
 * `auth_type` is always `"bearer"` - an OAuth grant is one human's consent at a
 * consent screen, and storing it as the organization's would attribute one
 * member's access to everybody and revoke it the day they left. There is no
 * endpoint to start an OAuth flow for an organization server.
 */
export interface OrgMcpConnectionRecord extends McpConnectionRecord {
  catalog_key: string | null;
}

interface OrgMcpConnectionList {
  items: OrgMcpConnectionRecord[];
  total: number;
}

export interface OrgMcpConnectionInput {
  name: string;
  url: string;
  auth_token?: string;
  allowed_tools?: string[] | null;
  is_enabled?: boolean;
  catalog_key?: string | null;
}

export interface OrgMcpConnectionPatch {
  name?: string;
  url?: string;
  /** `""` clears the stored credential. Omit to leave it alone. */
  auth_token?: string;
  allowed_tools?: string[];
  clear_allowed_tools?: boolean;
  is_enabled?: boolean;
}

const ROOT = "/mcp-connections";

export async function listOrgMcpConnections(): Promise<OrgMcpConnectionRecord[]> {
  const data = await apiClient.get<OrgMcpConnectionList>(ROOT);
  return data.items;
}

export async function createOrgMcpConnection(
  input: OrgMcpConnectionInput,
): Promise<OrgMcpConnectionRecord> {
  return apiClient.post<OrgMcpConnectionRecord>(ROOT, input);
}

export async function updateOrgMcpConnection(
  id: string,
  patch: OrgMcpConnectionPatch,
): Promise<OrgMcpConnectionRecord> {
  return apiClient.patch<OrgMcpConnectionRecord>(`${ROOT}/${id}`, patch);
}

export async function deleteOrgMcpConnection(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${id}`);
}

export async function testOrgMcpConnection(id: string): Promise<McpConnectionTestResult> {
  return apiClient.post<McpConnectionTestResult>(`${ROOT}/${id}/test`);
}
