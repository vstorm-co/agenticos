// Mirrors OrgRoleName in the backend permission catalog - the roles a member
// can hold. What each role may actually do lives in ROLE_PERMS server-side and
// reaches the UI via /me/permissions, never hardcoded here.
export type OrgRole = "owner" | "admin" | "builder" | "operator" | "member" | "viewer";

/**
 * Who made a membership - in an organization or in a group.
 *
 * `directory` is the sign-in sync: a directory group mapping placed the person
 * when they signed in through LDAP, Kerberos or an OIDC groups claim, and the
 * sync keeps that row in step with the directory, changing and removing it.
 * `manual` is everything else, which the sync never touches. Changing a
 * directory member's role by hand takes the membership over: it becomes `manual`.
 */
export type MembershipSource = "manual" | "directory";

/**
 * How a hosted page's or a widget's microphone turns speech into text.
 *
 * `off` hides the microphone, `browser` uses the browser vendor's own speech
 * service (absent in Firefox), and `server` records the audio and sends it
 * through this deployment to the agent's speech-to-text provider.
 */
export type DictationEngine = "off" | "browser" | "server";

/**
 * What the browser records a dictation in: `wav` is 16 kHz mono 16-bit PCM the
 * page builds itself, and the default; `webm` is whatever `MediaRecorder` makes,
 * sent only where the deployment accepts compressed audio and the provider
 * takes it. The backend decides which, so the composer, the hosted page and the
 * widget never keep a list of their own.
 */
export type RecordingFormat = "webm" | "wav";

export type ProactiveTiming = "fixed" | "before_work";

/** What the proactivity settings send: the fields named change, the rest stay. */
export interface ProactivityChanges {
  proactive_enabled?: boolean;
  proactive_model_profile_id?: string | null;
  proactive_limit_usd?: number;
  proactive_days?: number[];
  proactive_hour?: number;
  proactive_timing?: ProactiveTiming;
  proactive_watches_enabled?: boolean;
  proactive_watch_min_minutes?: number;
}

/** What the welcome-message settings send. */
export interface WelcomeDmChanges {
  welcome_dm_enabled?: boolean;
  welcome_dm_text?: string | null;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  avatar_url: string | null;
  /** Chosen default-avatar colour slot (1..10); null is auto from the id. */
  avatar_color: number | null;
  is_personal: boolean;
  /**
   * The deployment's default organization: every new account joins it, a request
   * naming no organization acts in it, and the console selects it when nothing
   * else is selected (#2156).
   */
  is_default?: boolean;
  owner_id: string;
  stripe_customer_id: string | null;
  subscription_tier: string;
  seats_limit: number | null;
  /**
   * Dollars every agent in this organization may spend between the first of the
   * month and the next, or `null` for no ceiling. It is the limit *over* each
   * agent's own: an agent can tighten it, never loosen it. A decimal string, as
   * the API serializes the column ("100.000000").
   */
  monthly_budget_usd: string | null;
  /** What background work may spend per person per month, as a decimal string; "0" is off. */
  proactive_limit_usd?: string;
  /** Whether the platform looks at each person's week on its own (#2301). Off by default. */
  proactive_enabled?: boolean;
  /** The model profile that look runs on; required to turn it on. */
  proactive_model_profile_id?: string | null;
  /** ISO weekdays it runs on, 1 = Monday, in each person's time zone. */
  proactive_days?: number[];
  /** The hour it runs at, in each person's time zone. */
  proactive_hour?: number;
  /** `before_work`: an hour before a person's working hours, else at `proactive_hour`. */
  proactive_timing?: ProactiveTiming;
  /** Whether people may have their own connections watched (#2301). Off by default. */
  proactive_watches_enabled?: boolean;
  /** The catalog servers a watch may read, by key; `null` for every one. */
  /** The most often any watch here may run, in minutes. */
  proactive_watch_min_minutes?: number;
  /** Whether a new member gets a direct message from the chat-app bots. Off by default. */
  welcome_dm_enabled?: boolean;
  /** What that message says, or `null` for the built-in greeting. */
  welcome_dm_text?: string | null;
  /**
   * Whether a chat session here may grant standing consent to gated tool calls -
   * `approve_all` in the composer's approval control. Off unless somebody who
   * holds `approvals:decide` turned it on: without a ceiling a Builder's
   * deliberate gate is one click from nothing in every conversation.
   *
   * The chat reads it to decide whether to offer the option at all. Who may then
   * take it is `approvals:decide`, which is a different question.
   */
  chat_may_waive_approvals: boolean;
  /**
   * A provider from the speech-to-text catalog: the default agents and channel
   * bots inherit when they transcribe with a provider.
   */
  speech_to_text_provider: string | null;
  /** A model that provider offers in the catalog. Set and cleared with the provider. */
  speech_to_text_model: string | null;
  /**
   * The vault key the pair is sent with, by id: an organization-visible API key
   * whose purpose is the provider. Null with a pair means it was deleted, and
   * dictation waits for another to be chosen.
   */
  speech_to_text_secret_id: string | null;
  /** An ISO-639-1 code recordings are pinned to, or `null` to auto-detect. */
  speech_to_text_language: string | null;
  /** The longest dictation in seconds (10-600); the composer's timer stops there. */
  dictation_max_seconds: number;
  created_at: string;
  updated_at: string | null;
}

/**
 * The speech settings the Voice card saves in one PATCH.
 *
 * The provider, model and key are optional and travel together: naming them
 * asks the server to check the pair against the catalog and the key against the
 * provider, so the card sends them only when one changed - a model withdrawn
 * since must not stop an engine switch.
 */
export type VoiceSettingsUpdate = Pick<
  Organization,
  "speech_to_text_language" | "dictation_max_seconds"
> &
  Partial<
    Pick<
      Organization,
      "speech_to_text_provider" | "speech_to_text_model" | "speech_to_text_secret_id"
    >
  >;

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
  source: MembershipSource;
  /** Whether the caller may change this member's role - the server's own answer
   *  to its rule, so the row shows a selector only where a change is accepted.
   *  Optional because only the members list computes it; absent reads as "no",
   *  which is the safe default for a control that would otherwise 403. */
  can_change_role?: boolean;
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

/** The reply to accepting an invitation: the organization joined (#2156). */
export interface InvitationAccepted {
  organization_id: string;
}

/** The reply to sending an invitation - the only one carrying the token. */
export interface InvitationCreated extends Invitation {
  invitation_token: string;
  /**
   * Whether the email carrying it was accepted for delivery.
   *
   * `null` where none was attempted, which is what an invite link is. The
   * inviter used to be told "invitation sent" in all three cases, including the
   * one where no mail service is configured and nobody was mailed at all.
   */
  email_delivered: boolean | null;
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
