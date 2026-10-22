import type { JsonSchema } from "@/types/agents";

/** How a backend signs in: its own secret fields, a Google account, an Entra app, or nothing. */
export type MirageCredential = "fields" | "google" | "microsoft" | "none";

export type MirageGroup = "files" | "mail" | "chat" | "work" | "data" | "servers" | "scratch";

/** One service the virtual terminal can mount, as `GET /agents/capabilities/mirage/backends` says it. */
export interface MirageBackend {
  name: string;
  title: string;
  group: MirageGroup;
  credential: MirageCredential;
  available: boolean;
  /** Why this deployment cannot mount it, when it cannot. */
  reason: string | null;
  /** The options an author fills; secrets and endpoint overrides are not in it. */
  options_schema: JsonSchema;
  secret_fields: string[];
  required_secrets: string[];
  /** Options naming a host, which must be on the operator's allowlist. */
  address_fields: string[];
}

export interface MirageBackendList {
  items: MirageBackend[];
  installed: boolean;
}

/** A mount as the spec stores it. */
export interface MirageMountSpec {
  path: string;
  backend: string;
  mode?: "read" | "write";
  approve_writes?: boolean;
  options?: Record<string, unknown>;
  secrets?: Record<string, string>;
  account?: { kind: "organization"; connection_id: string } | { kind: "personal" } | null;
}

/** A connected account: an OAuth grant a mount signs in as. */
export interface ConnectedAccount {
  id: string;
  provider: "google";
  email: string;
  scopes: string[];
  owner: "personal" | "organization";
  /** Its grant stopped working and it has to be connected again. */
  needs_reconnect: boolean;
  created_at: string;
}

export interface ConnectedAccountList {
  items: ConnectedAccount[];
  total: number;
}
