import type { Locale } from "@/lib/locales";

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  /**
   * An address asked for and not yet confirmed, or null.
   *
   * A change is staged rather than applied: the account keeps receiving mail at
   * `email` until the link sent to the new address comes back, so a form that
   * showed the old value and said nothing would read as a change that did not
   * take. Optional because a persisted store may predate it.
   */
  pending_email?: string | null;
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
   * The console language the person chose, on every device - by the menu or by
   * asking an agent. Null until they choose, and the cookie decides as before.
   */
  locale?: Locale | null;
  /** The IANA zone agents read the person's times in; taken from the browser when unset. */
  time_zone?: string | null;
  /** The person's role, as every agent is told it. */
  job_title?: string | null;
  /** What the person works on, as every agent is told it. */
  about?: string | null;
  /** When the person works, in their own time zone - knowledge for the agent only. */
  working_hours?: WorkingHours | null;
  /** This person left themselves out of the organization's nightly look (#2301). */
  proactive_opt_out?: boolean;
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

/**
 * A directory (LDAP) sign-in. A username rather than an email address, because
 * the directory binds with the account's own name.
 */
export interface DirectoryLoginRequest {
  username: string;
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

/** When a person works: ISO weekdays (1 = Monday) and HH:MM in their own zone (#2301). */
export interface WorkingHours {
  days: number[];
  start: string;
  end: string;
}
