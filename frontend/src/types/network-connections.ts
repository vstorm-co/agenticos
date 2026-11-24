export type NetworkConnectionScope = "user" | "org";
export type NetworkDesiredState = "active" | "paused" | "revoked";
export type NetworkAuthState =
  | "not_connected"
  | "sign_in_required"
  | "approval_required"
  | "authenticated"
  | "expired"
  | "error";
export type NetworkRuntimeState = "stopped" | "starting" | "running" | "unavailable";
export type NetworkCleanupState = "none" | "pending" | "manual" | "complete";

export interface NetworkConnection {
  id: string;
  organization_id: string;
  owner_user_id: string | null;
  scope: NetworkConnectionScope;
  name: string;
  desired_state: NetworkDesiredState;
  auth_state: NetworkAuthState;
  runtime_state: NetworkRuntimeState;
  cleanup_state: NetworkCleanupState;
  tailnet_name: string | null;
  node_id: string | null;
  last_seen_at: string | null;
  last_error_code: string | null;
  created_at: string;
  updated_at: string;
  can_manage: boolean;
}

export interface NetworkConnectionList {
  items: NetworkConnection[];
  total: number;
  available: boolean;
}

/** Private, short-lived enrollment data. Keep it in component state only. */
export interface NetworkEnrollment {
  attempt_id: string | null;
  expires_at: string | null;
  login_url: string | null;
}

export interface NetworkPeer {
  id: string;
  hostname: string;
  dns_name: string | null;
  ips: string[];
  online: boolean;
  os: string;
}

export interface NetworkPeerList {
  items: NetworkPeer[];
  observed_at: string | null;
}

export interface NetworkConnectionScopeKey {
  userId: string;
  orgId: string;
}
