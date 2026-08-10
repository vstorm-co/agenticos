/** Channel bots - the organization-level bindings to Slack, Telegram, Mattermost. */

export type ChannelPlatform = "telegram" | "slack" | "mattermost";

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

export interface ChannelBot {
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
  /** Whether Socket Mode (dev polling) can run - never the token itself. */
  has_slack_app_token: boolean;
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
  /** Slack only: this app's xapp- token, for Socket Mode (dev). */
  slack_app_token?: string;
}
