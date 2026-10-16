/**
 * API client for saving a drawing from the conversation as an app (#2171).
 *
 * The server rebuilds the visual from the transcript, revisions applied, rather
 * than taking its bytes from here: the app is exactly what the agent drew.
 */

import { apiClient } from "./api-client";

export interface VisualPublish {
  /** The app's handle; an existing one of the caller's gets a new version. */
  name: string;
  title?: string;
}

export interface VisualPublished {
  artifact_id: string;
  version: number;
  name: string;
  title: string;
  created: boolean;
  /** Identical to the app's current version, so no version was added. */
  unchanged: boolean;
  /** Where the app opens in the console. */
  url: string;
}

export function publishVisual(
  conversationId: string,
  visualId: string,
  data: VisualPublish,
): Promise<VisualPublished> {
  return apiClient.post<VisualPublished>(
    `/conversations/${conversationId}/visuals/${encodeURIComponent(visualId)}/publish`,
    data,
  );
}
