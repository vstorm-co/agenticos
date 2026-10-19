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

/** One drawing the caller was drawn, as the dashboard lists it. */
export interface VisualListItem {
  id: string;
  conversation_id: string;
  tool_call_id: string;
  agent_id: string | null;
  title: string;
  kind: "svg" | "html" | "mermaid";
  revision_of: string | null;
  artifact_id: string | null;
  has_thumbnail: boolean;
  created_at: string;
}

export function listRecentVisuals(limit: number): Promise<{ items: VisualListItem[] }> {
  return apiClient.get<{ items: VisualListItem[] }>(`/visuals?limit=${limit}`);
}

/** Where a drawing's thumbnail is read, through the console's own proxy. */
export function visualThumbnailUrl(visualId: string): string {
  return `/api/visuals/${visualId}/thumbnail`;
}

/** Keep the thumbnail this console made of a drawing it just rendered. */
export function putVisualThumbnail(
  conversationId: string,
  visualId: string,
  png: Blob,
): Promise<void> {
  return apiClient.upload<void>(
    `/conversations/${conversationId}/visuals/${encodeURIComponent(visualId)}/thumbnail`,
    new File([png], "thumbnail.png", { type: "image/png" }),
  );
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

/**
 * One picture a visual uses, as a `data:` URI the drawing's frame can show.
 *
 * Read through the console's own session and put into the drawing as data: the
 * frame has no network and must not be given one for a picture.
 */
export async function getVisualImage(
  conversationId: string,
  visualId: string,
  name: string,
): Promise<string> {
  const response = await apiClient.raw(
    `/conversations/${conversationId}/visuals/${encodeURIComponent(visualId)}/images/${encodeURIComponent(name)}`,
  );
  const blob = await response.blob();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("unreadable"));
    reader.readAsDataURL(blob);
  });
}
