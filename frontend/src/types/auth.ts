export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  is_active: boolean;
  role?: string;
  created_at: string;
  avatar_url?: string | null;
  /** ISO timestamp when the user finished the onboarding wizard. `null` means
   *  the wizard hasn't been completed yet - middleware/banner uses this. */
  onboarding_completed_at?: string | null;
  /** Notification opt-outs, mirrored from the `notify_*` columns. Optional
   *  because a persisted store may predate them; absent means subscribed,
   *  which matches the server default. */
  notify_budget_alerts?: boolean;
  notify_approval_requests?: boolean;
  notify_usage_reports?: boolean;
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
