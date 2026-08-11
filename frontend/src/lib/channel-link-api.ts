/**
 * Claiming a chat account for the signed-in person, and seeing what is claimed.
 *
 * The URL arrives in a chat and carries a token; the session says who is
 * accepting. Both halves are needed, and only the second is trustworthy on its
 * own - which is why confirming is a POST from an authenticated browser rather
 * than anything the bot can do by itself.
 */

import { apiClient } from "./api-client";

export interface ChannelLinkRequest {
  platform: string;
  platform_username: string | null;
  platform_display_name: string | null;
  expires_at: string;
}

/** An agent a connected chat account can reach. */
export interface LinkedAgent {
  id: string;
  name: string;
  slug: string;
  has_avatar: boolean;
}

/**
 * One bot a chat account has been used with, and what answers there.
 *
 * A chat account is keyed on the platform and the account, never on a bot - so
 * "Mattermost" was the whole of what a row could say about itself, which on a
 * deployment with two Mattermost servers does not say which company's chat was
 * connected. Resolved server-side from the sessions the account has, and
 * narrowed to the organizations this person belongs to and the agents they may
 * see.
 */
export interface LinkedPlace {
  bot_id: string;
  bot_name: string;
  /** The server, for the platforms that have one. Null on Slack and Telegram. */
  host: string | null;
  agents: LinkedAgent[];
}

export interface ChannelIdentity {
  id: string;
  platform: string;
  platform_username: string | null;
  platform_display_name: string | null;
  is_active: boolean;
  created_at: string;
  /** Where this account has been used. Empty until it has been used anywhere. */
  places: LinkedPlace[];
}

interface ChannelIdentityList {
  items: ChannelIdentity[];
  total: number;
}

const ROOT = "/me/channel-link";

export async function readChannelLink(token: string): Promise<ChannelLinkRequest> {
  return apiClient.get<ChannelLinkRequest>(`${ROOT}/${encodeURIComponent(token)}`);
}

export async function confirmChannelLink(token: string): Promise<ChannelLinkRequest> {
  return apiClient.post<ChannelLinkRequest>(`${ROOT}/${encodeURIComponent(token)}`, {});
}

export async function listLinkedAccounts(): Promise<ChannelIdentity[]> {
  const data = await apiClient.get<ChannelIdentityList>(ROOT);
  return data.items;
}

export async function unlinkAccount(identityId: string): Promise<void> {
  await apiClient.delete<void>(`${ROOT}/${identityId}`);
}
