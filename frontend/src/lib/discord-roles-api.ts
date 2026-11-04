/**
 * API client for a Discord bot's server role mappings (#2569).
 *
 * Every call needs `channels:manage` and `members:manage`; a mapping that names
 * an organization role needs `roles:manage` as well, and a role the caller's own
 * strictly outranks - to make it and to delete it.
 */

import { apiClient } from "./api-client";
import type {
  DiscordRoleMapping,
  DiscordRoleMappingCreate,
  DiscordRoleMappingList,
  DiscordServerList,
} from "@/types/channels";

const bot = (botId: string) => `/channels/bots/${botId}`;

/** Read from Discord on every call; a 503 when Discord does not answer. */
export async function listDiscordServers(botId: string): Promise<DiscordServerList> {
  return apiClient.get<DiscordServerList>(`${bot(botId)}/discord-servers`);
}

export async function listDiscordRoleMappings(botId: string): Promise<DiscordRoleMappingList> {
  return apiClient.get<DiscordRoleMappingList>(`${bot(botId)}/role-mappings`);
}

/** Refused with a 409 when the role is already mapped for this bot. */
export async function createDiscordRoleMapping(
  botId: string,
  input: DiscordRoleMappingCreate,
): Promise<DiscordRoleMapping> {
  return apiClient.post<DiscordRoleMapping>(`${bot(botId)}/role-mappings`, input);
}

/** What the mapping gave people is taken back by the next role sync. */
export async function deleteDiscordRoleMapping(botId: string, mappingId: string): Promise<void> {
  await apiClient.delete<void>(`${bot(botId)}/role-mappings/${mappingId}`);
}
