/**
 * Claiming a chat account for the signed-in person.
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

const ROOT = "/me/channel-link";

export async function readChannelLink(token: string): Promise<ChannelLinkRequest> {
  return apiClient.get<ChannelLinkRequest>(`${ROOT}/${encodeURIComponent(token)}`);
}

export async function confirmChannelLink(token: string): Promise<ChannelLinkRequest> {
  return apiClient.post<ChannelLinkRequest>(`${ROOT}/${encodeURIComponent(token)}`, {});
}
