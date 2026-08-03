/**
 * API client for the places this organization's sandboxes run.
 *
 * The same shape as the organization's MCP servers and its model profiles, for
 * the same reason: an agent names one by id, so changing where sandboxes run is
 * one edit here rather than a republish of every agent.
 *
 * No function in this file sends or receives a credential. `secret_id` points at
 * a vault entry; the token behind it authorises opening a session, and a session
 * runs commands on the host holding the Docker socket - so it never leaves the
 * backend. The policy call is proxied through our own API for exactly that
 * reason: reaching the sandbox service needs the token, and a browser must not
 * have it.
 */

import { apiClient } from "./api-client";

/** What a sandbox connection points at. */
export type SandboxConnectionKind = "docker" | "daytona";

export interface SandboxConnectionRecord {
  id: string;
  name: string;
  kind: SandboxConnectionKind;
  /** Where a `docker` service answers. Null for Daytona, which has its own. */
  base_url: string | null;
  /** The vault entry holding the token. An id - never the value. */
  secret_id: string | null;
  default_runtime: string | null;
  /** Which connection an agent naming none resolves to. One per organization. */
  is_default: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
}

interface SandboxConnectionList {
  items: SandboxConnectionRecord[];
  total: number;
}

export interface SandboxConnectionInput {
  name: string;
  kind: SandboxConnectionKind;
  base_url?: string | null;
  secret_id?: string | null;
  default_runtime?: string | null;
  is_default?: boolean;
}

export interface SandboxConnectionPatch {
  name?: string;
  kind?: SandboxConnectionKind;
  base_url?: string | null;
  secret_id?: string | null;
  default_runtime?: string | null;
  is_default?: boolean;
  is_active?: boolean;
}

/**
 * One runtime the service will accept, with the ceilings in force behind it.
 *
 * Read from the service on every call rather than stored: these are its own boot
 * configuration, so a copy would disagree the first time an operator restarted
 * it with a different limit. There is deliberately no endpoint to write them - a
 * browser that could reconfigure the process holding the Docker socket would own
 * the host.
 */
export interface SandboxRuntime {
  alias: string;
  image: string | null;
  description: string;
  builds: boolean;
  mem_limit: string | null;
  cpus: number | null;
  network_mode: string | null;
}

export interface SandboxPolicy {
  kind: string;
  runtimes: SandboxRuntime[];
  default_runtime: string | null;
  max_sessions: number | null;
  max_open_sessions: number | null;
  max_sessions_per_tenant: number | null;
  idle_timeout: number | null;
  workspace_root: string | null;
  persist_containers: boolean | null;
}

/**
 * One sandbox open on a connection.
 *
 * `tenant` is deliberately absent: the backend drops every session belonging to
 * another organization before answering, so a field here would be a second place
 * for that to be believed. The attribution fields come from `agent_workspaces`
 * and are absent for a run-scoped sandbox, which has no row by design.
 */
export interface SandboxSession {
  session_id: string;
  runtime: string;
  alive: boolean;
  state: string;
  created_at: number;
  last_activity: number;
  idle_seconds: number;
  usage: {
    memory_bytes?: number | null;
    memory_limit_bytes?: number | null;
    cpu_percent?: number | null;
    pids?: number | null;
  } | null;
  agent_id: string | null;
  conversation_id: string | null;
  scope: string | null;
}

export interface SandboxSessionList {
  sessions: SandboxSession[];
  limit: number | null;
  open_limit: number | null;
  tenant_limit: number | null;
}

/** One operation against a sandbox. Never file contents, never command output. */
export interface SandboxEvent {
  seq: number;
  at: number;
  op: string;
  target: string;
  ok: boolean;
  detail: string;
  duration_ms: number;
}

export interface SandboxEventList {
  events: SandboxEvent[];
  latest_seq: number;
}

const ROOT = "/sandbox-connections";

export async function listSandboxConnections(): Promise<SandboxConnectionRecord[]> {
  const data = await apiClient.get<SandboxConnectionList>(ROOT);
  return data.items;
}

export async function createSandboxConnection(
  input: SandboxConnectionInput,
): Promise<SandboxConnectionRecord> {
  return apiClient.post<SandboxConnectionRecord>(ROOT, input);
}

export async function updateSandboxConnection(
  id: string,
  patch: SandboxConnectionPatch,
): Promise<SandboxConnectionRecord> {
  return apiClient.patch<SandboxConnectionRecord>(`${ROOT}/${id}`, patch);
}

export async function deleteSandboxConnection(id: string): Promise<void> {
  await apiClient.delete(`${ROOT}/${id}`);
}

/** What the service allows, asked of the service. Throws when it cannot answer. */
export async function readSandboxPolicy(id: string): Promise<SandboxPolicy> {
  return apiClient.get<SandboxPolicy>(`${ROOT}/${id}/policy`);
}

/**
 * The sandboxes this organization has open on one connection.
 *
 * `usage` costs the service a daemon round trip per sandbox, so it is opt-in
 * rather than something a listing pays for on load.
 */
export async function listSandboxSessions(id: string, usage = false): Promise<SandboxSessionList> {
  return apiClient.get<SandboxSessionList>(`${ROOT}/${id}/sessions?usage=${usage}`);
}

/** What has been done to one sandbox. `after` is the sequence already held. */
export async function readSandboxEvents(
  id: string,
  sessionId: string,
  after = 0,
): Promise<SandboxEventList> {
  return apiClient.get<SandboxEventList>(
    `${ROOT}/${id}/sessions/${sessionId}/events?after=${after}`,
  );
}
