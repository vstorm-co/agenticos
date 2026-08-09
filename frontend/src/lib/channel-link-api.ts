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

export interface ChannelIdentity {
  id: string;
  platform: string;
  platform_username: string | null;
  platform_display_name: string | null;
  is_active: boolean;
  created_at: string;
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
