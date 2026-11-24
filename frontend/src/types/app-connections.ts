/** Public app connection metadata. Provider credentials never cross this boundary. */
export interface AppConnection {
  id: string;
  catalog_key: string;
  toolkit: string;
  name: string;
  label: string | null;
  identity: string | null;
  status: "pending" | "connected" | "expired" | "failed" | "disabled";
  is_enabled: boolean;
  is_default: boolean;
  authorized: boolean;
  readiness: "authorization_required" | "authorization_verified" | "unavailable";
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
  app: ConnectedAppDefinition;
}

export interface ConnectedAppDefinition {
  key: string;
  toolkit: string;
  name: string;
  description: string;
  category: string;
  configured: boolean;
  availability: "ready" | "setup_required" | "unavailable";
  approval_required: boolean;
  action_count: number;
  actions: {
    name: string;
    label: string;
    read_only: boolean;
    side_effecting: boolean;
    scopes: string[];
  }[];
}

export interface AppConnectionCatalog {
  configured: boolean;
  catalog_available: boolean;
  apps: ConnectedAppDefinition[];
  next_cursor: string | null;
}

export interface AppConnectionAuthorization {
  connection_id: string;
  attempt_id: string;
  redirect_url: string;
  expires_at: string;
}

/** Identity verification callbacks can carry only session_uri. */
export interface AppConnectionCallback {
  attempt_id?: string;
  connected_account_id?: string;
  session_uri?: string;
}

export interface AppConnectionScope {
  userId: string;
  orgId: string | null;
}
