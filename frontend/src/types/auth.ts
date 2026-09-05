export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  /** Platform-superadmin flag - the gate for the /admin surface. Optional
   *  because a persisted store may predate it; absent means not an admin. */
  is_app_admin?: boolean;
  created_at: string;
  avatar_url?: string | null;
  /** Chosen default-avatar colour slot (1..10); null/absent is auto from the id. */
  avatar_color?: number | null;
  /** ISO timestamp when the user finished the onboarding wizard. `null` means
   *  the wizard hasn't been completed yet - middleware/banner uses this. */
  onboarding_completed_at?: string | null;
  /** Notification opt-outs, mirrored from the `notify_*` columns. Optional
   *  because a persisted store may predate them; absent means subscribed,
   *  which matches the server default. */
  notify_budget_alerts?: boolean;
  notify_approval_requests?: boolean;
  notify_usage_reports?: boolean;
  /**
   * Set while an administrator is acting as this account, and what the banner
   * is drawn from. Absent - not merely null - on a persisted store that predates
   * it, which reads the same as nobody acting as anybody.
   */
  impersonation?: Impersonation | null;
}

/** An administrator acting as the signed-in account: who, and until when. */
export interface Impersonation {
  session_id: string;
  impersonator: {
    id: string;
    email: string;
    full_name?: string | null;
  };
  expires_at: string;
}

export interface Session {
  id: string;
  device_name?: string | null;
  device_type?: string | null;
  ip_address?: string | null;
  is_current: boolean;
  created_at: string;
  last_used_at: string;
}

/** One page of sessions. `total` counts the user's sessions, not the page. */
export interface SessionListResponse {
  items: Session[];
  total: number;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
}

export interface RegisterRequest {
  email: string;
  password: string;
  full_name?: string;
  /**
   * The invitation this sign-up is arriving through, when the form was reached
   * from one.
   *
   * It admits an address a deployment's sign-up policy would otherwise refuse -
   * and it is the only proof that can admit a shareable link constraining no
   * address at all. It grants nothing else: joining the organization is still a
   * separate accept once there is a session.
   */
  invitation_token?: string;
}

export interface RegisterResponse {
  id: string;
  email: string;
  full_name?: string | null;
}

export interface RefreshTokenRequest {
  refresh_token: string;
}

export interface RefreshTokenResponse {
  access_token: string;
  token_type: string;
  refresh_token?: string;
}

export interface AuthState {
  user: User | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
}
