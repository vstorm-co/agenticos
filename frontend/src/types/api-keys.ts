import type { Permission } from "./permissions";

/** Where a key stands: usable, past its expiry, or revoked by a person. */
export type ApiKeyStatus = "active" | "expired" | "revoked";

export type ApiKeyPresetId = "read_only" | "knowledge_ingest" | "full_access";

/** An organization API key as a list shows it - never the key itself. */
export interface ApiKey {
  id: string;
  name: string;
  /** The key's first characters, enough to recognise it in a list or a log. */
  prefix: string;
  scopes: Permission[];
  /** The member whose authority the key carries. */
  user_id: string;
  issuer_email: string;
  status: ApiKeyStatus;
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

/** The one response that holds the key itself. */
export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface ApiKeyList {
  items: ApiKey[];
  total: number;
}

export interface ApiKeyPreset {
  id: ApiKeyPresetId;
  scopes: Permission[];
}

/** What the caller may put on a key: their own permissions, and the presets over them. */
export interface ApiKeyScopeCatalog {
  scopes: Permission[];
  presets: ApiKeyPreset[];
}

export interface ApiKeyCreateInput {
  name: string;
  scopes: Permission[];
  expires_at: string | null;
}
