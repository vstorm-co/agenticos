/** Channel bots - the organization-level bindings to Slack, Telegram, Mattermost, Teams, Discord, WhatsApp. */

export type ChannelPlatform =
  "telegram" | "slack" | "mattermost" | "teams" | "discord" | "whatsapp";

/** How a streamed answer shows its tool calls: one row each, or one plan (#2084). */
export type StepDisplay = "timeline" | "plan";

/**
 * How a bot answers, beyond what it says (#2084): a reaction on the question as it
 * arrives, an answer streamed natively where the platform draws it (Slack), its
 * tool calls as a timeline or a plan, and thumbs under it to rate it.
 */
export interface AnswerStyle {
  /** An emoji's name without colons, `eyes`; null reacts with nothing. */
  ack_reaction: string | null;
  stream_answers: boolean;
  step_display: StepDisplay;
  rate_answers: boolean;
}

/**
 * When an agent says what a turn cost, and when it only records it.
 *
 * `off` is unspoken, not unmeasured - the report is logged either way, because
 * "the bot went quiet" is a question somebody asks days later.
 *
 * Carried on the *binding* rather than on the bot: it is one of the things an
 * agent's author decides about a surface, beside the extra instructions and the
 * channel lookups. See `src/types/exposures.ts`.
 */
export interface UsageReporting {
  mode: "off" | "always" | "near_limit" | "every_n";
  /** What `near_limit` compares the budget and the workspace against. */
  near_limit_percent: number;
  /** The n in `every_n`, counted per chat rather than per bot. */
  every_n: number;
}

export interface ChannelAccessPolicy {
  mode: "open" | "whitelist" | "jwt_linked" | "group_only";
  whitelist: string[];
  allowed_groups: string[];
  /** Explicit server approvals for Discord; absent or empty permits DMs only. */
  discord_guild_ids?: string[];
  require_link: boolean;
  rate_limit_rpm: number;
  denied_message: string;
  respond_to_broadcasts?: boolean;
  /** WhatsApp only: answer a private chat from somebody with no linked account, as the agent. */
  answer_unlinked_direct?: boolean;
  /** WhatsApp only: take files from such a customer. */
  accept_customer_files?: boolean;
}

/** One thing a customer with no account can reach through the agent. */
export interface PublicLineReach {
  kind:
    | "knowledge"
    | "context"
    | "skills"
    | "tables"
    | "web"
    | "code"
    | "generation"
    | "delegates"
    | "mcp"
    | "files";
  names: string[];
  /** `outside_ledger`: the use is not counted in the spending limit. */
  detail: "outside_ledger" | null;
  /** What may be done in each table, for a `tables` reach. */
  grants: { name: string; operations: string[] }[];
  may_create: boolean;
}

/** What a public line would answer with, and what bounds it - `GET /channels/bots/{id}/public-line`. */
export interface PublicLine {
  answers_unlinked: boolean;
  agent_name: string | null;
  agent_version: number | null;
  /** Decimal values arrive as strings. */
  agent_monthly_usd: string | null;
  organization_monthly_usd: string | null;
  can_turn_on: boolean;
  accept_customer_files: boolean;
  voice: "off" | "refused_no_org_cap" | "on";
  rate_limit_rpm: number;
  approval_expiry_hours: number;
  recording_max_mb: number;
  file_max_mb: number;
  reaches: PublicLineReach[];
  refused: (
    | "memory"
    | "conversation_search"
    | "artifacts"
    | "workflows"
    | "background_tasks"
    | "platform_mcp"
  )[];
}

export interface ChannelBot extends AnswerStyle {
  access_policy: ChannelAccessPolicy;
  id: string;
  platform: ChannelPlatform;
  name: string;
  is_active: boolean;
  webhook_mode: boolean;
  webhook_url: string | null;
  /**
   * The bot's own server, for a self-hosted platform. An address rather than a
   * credential, so it is read back - Mattermost only; the others have one
   * address for everybody.
   */
  api_base_url: string | null;
  /** Whether an inbound webhook can be authenticated - never the secret itself. */
  has_webhook_secret: boolean;
  /** Whether inbound Slack events can be verified - never the secret itself. */
  has_slack_signing_secret: boolean;
  /** Whether Socket Mode can run - never the token itself. */
  has_slack_app_token: boolean;
  /** Mattermost only: whether `/agent` requests can be verified - never the token itself. */
  has_command_token: boolean;
  /** Mattermost only: the request URL to paste into the `/agent` slash command. */
  command_url: string | null;
  /**
   * Teams only: the Azure Bot's app and tenant (#1985). Identifiers, not
   * credentials - the app package is built from them; the client secret is the
   * token and is never read back.
   */
  teams_app_id?: string | null;
  teams_tenant_id?: string | null;
  /** Teams only: the messaging endpoint to paste into the Azure Bot resource. */
  messaging_endpoint?: string | null;
  /**
   * WhatsApp only (#2076): the Cloud API registration. Identifiers, not
   * credentials; the access token is the token, the Meta app secret the webhook
   * secret, and the verify token is sealed and never read back.
   */
  whatsapp_phone_number_id?: string | null;
  whatsapp_account_id?: string | null;
  has_whatsapp_verify_token?: boolean;
  /** WhatsApp only: the callback URL to paste into the Meta app's webhook setup. */
  whatsapp_callback_url?: string | null;
  /** WhatsApp only: the template a late answer goes out in; null when none is set. */
  whatsapp_late_template?: WhatsAppTemplate | null;
  /**
   * Whether the socket this bot receives on is actually up.
   *
   * `null` for a webhook bot, which holds no connection (a WhatsApp bot reports a
   * send-health state instead), and for a polling bot nothing is known about - no
   * Redis, or no supervisor has touched it since the entry expired. Unknown is its own
   * answer: a polling bot whose stream never opened used to look identical to a working
   * one, and claiming the reverse would put a fault on every bot in a deployment that
   * cannot report.
   */
  connection: ChannelConnection | null;
  /** Whether voice notes are transcribed here at all; off wins over every pair. */
  transcribe_voice_notes: boolean;
  /**
   * Which model transcribes voice notes here, or null to inherit the agent's or
   * the organization's.
   *
   * A pair that moves together: a provider with no model has nothing to call and
   * a model with no provider has nowhere to send it. Read back plainly - these
   * are choices somebody made, not credentials.
   */
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
  /**
   * The vault key the bot's own pair is sent with, by id: an organization-visible
   * API key for the provider. Null with a pair means it was deleted.
   */
  speech_to_text_secret_id: string | null;
  /**
   * What "inherit" resolves to for this bot. On the single-bot read only - the
   * listing leaves it out - and null where nothing resolves.
   */
  inherited_speech_to_text?: InheritedSpeechToText | null;
  /**
   * Who answers here, from the active bindings.
   *
   * A bot with none is registered and silent, which is the state somebody opens
   * the channels page to explain - and a listing that named only the bot could
   * not tell it from one that is working.
   */
  agents: BotAgent[];
  created_at: string;
  updated_at?: string | null;
}

/** The engine a bot's voice notes go to when it inherits rather than names one. */
export interface InheritedSpeechToText {
  provider: string;
  model: string;
  language: string | null;
  /** Whether the bot's agent or its organization chose the pair. */
  pair_source: "agent" | "organization";
  language_source: "agent" | "organization" | null;
  /** The agent the bot serves. */
  agent_name: string | null;
  /** Whether the level the pair comes from names a key that is still usable. */
  has_key: boolean;
}

/** The state of the inbound socket a polling bot receives on. */
export interface ChannelConnection {
  state: "up" | "down";
  /** What an operator can do about it. Never a vendor exception's text. */
  reason: string | null;
}

/** An agent that answers on one bot. */
export interface BotAgent {
  id: string;
  name: string;
  slug: string;
  has_avatar: boolean;
}

export interface ChannelBotList {
  items: ChannelBot[];
  total: number;
}

export interface ChannelBotCreate {
  access_policy?: Partial<ChannelAccessPolicy>;
  platform: ChannelPlatform;
  name: string;
  /** The bot token as issued by the platform. Encrypted at rest, never read back. */
  token: string;
  /**
   * Mattermost only, and required there: the bot's own server. Mattermost is
   * self-hosted, so a bot that does not know its server cannot reply, cannot
   * open its event stream and cannot fetch an attachment.
   */
  api_base_url?: string;
  /**
   * The shared secret an inbound webhook is authenticated against. Paste the
   * token Mattermost shows when the outgoing webhook is created; Telegram
   * generates one and is handed it at registration.
   */
  webhook_secret?: string;
  /** Slack only: this app's signing secret - inbound events are verified with it. */
  slack_signing_secret?: string;
  /** Slack only: this app's xapp- token, for Socket Mode. */
  slack_app_token?: string;
  /** Omitted inherits; `false` never transcribes. */
  transcribe_voice_notes?: boolean;
  /**
   * Slack: `true` when Slack calls this deployment's address, `false` when the
   * deployment connects out to Slack (Socket Mode) and needs no public address.
   */
  webhook_mode?: boolean;
  /** Mattermost only: the token Mattermost shows for the `/agent` slash command. */
  command_token?: string;
  /** Teams only, and required there: the Azure Bot's Microsoft App ID. */
  teams_app_id?: string;
  /** Teams only, and required there: the tenant the single-tenant bot is registered in. */
  teams_tenant_id?: string;
  /** WhatsApp only, and required there: the business phone number's Cloud API id. */
  whatsapp_phone_number_id?: string;
  /** WhatsApp only, and required there: the WhatsApp Business Account that owns it. */
  whatsapp_account_id?: string;
  /** WhatsApp only, and required there: the token entered in Meta's webhook setup. */
  whatsapp_verify_token?: string;
  ack_reaction?: string | null;
  stream_answers?: boolean;
  step_display?: StepDisplay;
  rate_answers?: boolean;
  speech_to_text_provider?: string | null;
  speech_to_text_model?: string | null;
  /** Required with a pair, refused without one. */
  speech_to_text_secret_id?: string | null;
}

/** A Teams channel or group chat a bot is in - where a trigger can post (#1985). */
export interface TeamsConversation {
  id: string;
  bot_id: string;
  name: string | null;
  conversation_type: "channel" | "groupChat";
  last_activity_at: string;
}

/**
 * What may be changed about a bot already registered.
 *
 * The platform is absent on purpose: it decides which credentials the row
 * carries and which transport reaches it, so changing it would be registering a
 * different bot under one id.
 *
 * Every field is optional and **an omitted credential keeps the stored one** -
 * the backend distinguishes omission from a value. That is the whole shape of
 * editing a sealed credential: it is never read back to be edited, so a blank
 * input means "leave it" rather than "clear it", and only a field somebody
 * typed into is sent.
 */
export interface ChannelBotUpdate {
  access_policy?: ChannelAccessPolicy;
  name?: string;
  /** A replacement bot token. Sealed at rest like the first one. */
  token?: string;
  /** Mattermost only: the bot's own server. An address, so it is read back. */
  api_base_url?: string;
  webhook_secret?: string;
  slack_signing_secret?: string;
  slack_app_token?: string;
  /** Slack only: which way the connection runs; see `ChannelBotCreate`. */
  webhook_mode?: boolean;
  command_token?: string;
  /**
   * WhatsApp only. The backend refuses these keys on any other platform, and
   * refuses a null for them on a WhatsApp bot: send a new value or omit them.
   */
  whatsapp_phone_number_id?: string;
  whatsapp_account_id?: string;
  whatsapp_verify_token?: string;
  /** WhatsApp only: the template chosen from Meta's list; null clears it, omitting leaves it. */
  whatsapp_late_template?: { name: string; language: string } | null;
  ack_reaction?: string | null;
  stream_answers?: boolean;
  step_display?: StepDisplay;
  rate_answers?: boolean;
  /** `false` never transcribes and clears the pair; never `null`. */
  transcribe_voice_notes?: boolean;
  /**
   * Both halves or neither; the server pairs them against the stored row. Null
   * clears the pair, which inherits - it used to mean off.
   */
  speech_to_text_provider?: string | null;
  speech_to_text_model?: string | null;
  /** The key goes with the pair: sent whenever the pair or the key moved. */
  speech_to_text_secret_id?: string | null;
}

/**
 * A WhatsApp message template as Meta lists it: approved, utility, with one
 * variable in its body, which is what a late answer fits into (#2076).
 */
export interface WhatsAppTemplate {
  name: string;
  language: string;
  body: string;
}

/**
 * A request to change what a public line answers with, waiting for somebody with
 * `channels:manage` - `GET /channels/binding-requests` and the per-agent listing.
 */
export interface BindingRequest {
  id: string;
  /** A new binding, a change of environment, or lifting a pause. */
  kind: "bind" | "environment" | "resume";
  status: "pending" | "approved" | "declined" | "voided";
  void_reason: "replaced" | "line_closed" | "bot_taken" | null;
  agent_id: string;
  agent_name: string;
  channel_bot_id: string;
  channel_bot_name: string;
  exposure_id: string | null;
  environment_id: string | null;
  session_scope: "run" | "conversation" | "channel" | "user" | "agent" | null;
  requester_user_id: string;
  requester_email: string | null;
  /** Written by the requester for whoever decides; never in a notification. */
  note: string | null;
  decided_by_user_id: string | null;
  decided_at: string | null;
  created_at: string;
}

/** What `POST /agents/{id}/exposures` answers with when an administrator has to decide. */
export interface DeferredBinding {
  status: "requested";
  request_id: string;
  /** Who decides, by name, when it is one person; null when several may. */
  waiting_for: string | null;
}

/** One person who wrote to a WhatsApp bot with no account - `channels:manage` sees the number. */
export interface WhatsAppCustomer {
  id: string;
  bsuid: string;
  phone: string | null;
  /** What the sender typed as their name; unverified. */
  profile_name: string | null;
  username: string | null;
  last_message_at: string | null;
  /** A member linked this chat account, so it is not a customer to forget. */
  linked: boolean;
}

/** What forgetting a customer removed, as counts; nothing in it names the customer. */
export interface CustomerErasure {
  identities: number;
  sessions: number;
  customers: number;
  conversations: number;
  workspaces: number;
  link_requests: number;
  prompts: number;
  runs_ended: number;
  approvals_ended: number;
  approvals_redacted: number;
  manifests: number;
  notifications: number;
  handback_jobs: number;
  handback_jobs_running: number;
}
