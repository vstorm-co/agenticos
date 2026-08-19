// Mirrors OrgRoleName in the backend permission catalog - the roles a member
// can hold. What each role may actually do lives in ROLE_PERMS server-side and
// reaches the UI via /me/permissions, never hardcoded here.
export type OrgRole = "owner" | "admin" | "builder" | "operator" | "member" | "viewer";

export interface Organization {
  id: string;
  name: string;
  slug: string;
  avatar_url: string | null;
  /** Chosen default-avatar colour slot (1..10); null is auto from the id. */
  avatar_color: number | null;
  is_personal: boolean;
  owner_id: string;
  stripe_customer_id: string | null;
  subscription_tier: string;
  seats_limit: number | null;
  /**
   * Dollars every agent in this organization may spend between the first of the
   * month and the next, or `null` for no ceiling. It is the limit *over* each
   * agent's own: an agent can tighten it, never loosen it.
   */
  monthly_budget_usd: number | null;
  created_at: string;
  updated_at: string | null;
}

export interface OrganizationMember {
  id: string;
  organization_id: string;
  user_id: string;
  role: OrgRole;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  /** Chosen default-avatar colour slot (1..10); null is auto from the id. */
  avatar_color: number | null;
  joined_at: string;
}

export interface OrganizationMemberList {
  items: OrganizationMember[];
  total: number;
}

// Without the token, because the API no longer sends one here: a token is a
// bearer credential - whoever holds it joins the organization as the role
// offered to somebody else's address - and this is what the members page lists.
// Revoking goes by `id`.
export interface Invitation {
  id: string;
  organization_id: string;
  /** Null makes this a shareable link rather than an invitation to one address. */
  email: string | null;
  role: OrgRole;
  status: "pending" | "accepted" | "expired" | "revoked";
  /** Links only: how many people it admits, null being unlimited. */
  max_uses?: number | null;
  used_count?: number;
  /**
   * Links only: how many people registered through it and have not joined yet.
   *
   * `max_uses` is compared against this *plus* `used_count` - registering spends a
   * use, because acceptance needs a session and a ceiling that ignored the gap let
   * one link mint accounts without bound. So the number shown against the maximum
   * is the sum, or the page says a spent link has a place left.
   */
  reserved_count?: number;
  /** Links only: restrict to addresses at this domain. */
  email_domain?: string | null;
  expires_at: string | null;
  created_at: string;
}

/** What an administrator asks for when minting a link. */
export interface NewInviteLink {
  role: OrgRole;
  max_uses?: number | null;
  email_domain?: string | null;
}

/** The reply to sending an invitation - the only one carrying the token. */
export interface InvitationCreated extends Invitation {
  invitation_token: string;
}

export interface InvitationList {
  items: Invitation[];
  total: number;
}

export interface OrganizationList {
  items: Organization[];
  total: number;
}

export interface CreateOrganizationInput {
  name: string;
  slug?: string;
}

export interface InviteMemberInput {
  email: string;
  role: OrgRole;
}
