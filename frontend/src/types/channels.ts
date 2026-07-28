/** Channel bots - the organization-level bindings to Slack, Telegram, Mattermost. */

export type ChannelPlatform = "telegram" | "slack" | "mattermost";

export interface ChannelBot {
  id: string;
  platform: ChannelPlatform;
  name: string;
  is_active: boolean;
  webhook_mode: boolean;
  webhook_url: string | null;
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
}
