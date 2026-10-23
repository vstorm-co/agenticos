/** Channel bots - the organization-level bindings to Slack, Telegram, Mattermost, Teams. */

export type ChannelPlatform = "telegram" | "slack" | "mattermost" | "teams";

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

export interface ChannelBot extends AnswerStyle {
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
   * Whether the socket this bot receives on is actually up.
   *
   * `null` for a webhook bot, which holds no connection, and for a polling bot
   * nothing is known about - no Redis, or no supervisor has touched it since the
   * entry expired. Unknown is its own answer: a polling bot whose stream never
   * opened used to look identical to a working one, and claiming the reverse
   * would put a fault on every bot in a deployment that cannot report.
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
