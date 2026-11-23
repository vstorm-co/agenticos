/**
 * API client for the sidebar items a person pinned.
 *
 * Pins are per user and per organization; the active organization travels on
 * the header `apiClient` already attaches, so these calls carry no org id.
 */

import { apiClient } from "./api-client";

export interface NavPins {
  item_ids: string[];
}

const ROOT = "/me/nav-pins";

export async function getNavPins(): Promise<NavPins> {
  return apiClient.get<NavPins>(ROOT);
}

export async function putNavPins(itemIds: string[]): Promise<NavPins> {
  return apiClient.put<NavPins>(ROOT, { item_ids: itemIds });
}
