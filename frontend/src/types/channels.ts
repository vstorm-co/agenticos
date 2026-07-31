/** Channel bots - the organization-level bindings to Slack, Telegram, Mattermost. */

export type ChannelPlatform = "telegram" | "slack" | "mattermost";

export interface ChannelBot {
  id: string;
  platform: ChannelPlatform;
  name: string;
  is_active: boolean;
  webhook_mode: boolean;
  webhook_url: string | null;
  /** Whether inbound Slack events can be verified - never the secret itself. */
  has_slack_signing_secret: boolean;
  /** Whether Socket Mode (dev polling) can run - never the token itself. */
  has_slack_app_token: boolean;
  created_at: string;
  updated_at?: string | null;
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
  /** Slack only: this app's signing secret - inbound events are verified with it. */
  slack_signing_secret?: string;
  /** Slack only: this app's xapp- token, for Socket Mode (dev). */
  slack_app_token?: string;
}
