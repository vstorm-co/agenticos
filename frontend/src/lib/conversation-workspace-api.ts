/**
 * The files an agent kept in one conversation.
 *
 * The conversation-scoped sibling of `sandbox-workspaces-api.ts`, and the
 * difference is who is asking: this is authorised by fetching the conversation
 * first, so it is a person looking at their own chat rather than an operator
 * looking across the organization.
 *
 * No sandbox is started to answer either call. A container-backed workspace is
 * read off the volume its service keeps, which is what lets a conversation from
 * last month list its files after the session was reaped.
 */

import { apiClient } from "./api-client";

export interface ConversationFile {
  path: string;
  size: number | null;
  is_dir: boolean;
}

export interface ConversationWorkspace {
  scope: string;
  backend: string;
  /**
   * Whose files these are, in words.
   *
   * Not decoration: under `agent` scope somebody opens a chat and finds a file
   * they never created, and without this line the reasonable reading is a leak.
   */
  owner_label: string;
  items: ConversationFile[];
  total: number;
  bytes_total: number;
  /**
   * Why this listing may be empty despite the workspace holding files.
   *
   * Not an error to render red. A service started with no `workspace_root` keeps
   * nothing on disk, so its files exist only while a sandbox runs - that is a
   * configuration somebody chose, and it has a one-line fix the message names.
   */
  unreadable_reason: string | null;
}

export interface ConversationFileContent {
  path: string;
  content: string;
  truncated: boolean;
}

export async function readConversationWorkspace(
  conversationId: string,
): Promise<ConversationWorkspace> {
  return apiClient.get<ConversationWorkspace>(`/conversations/${conversationId}/workspace`);
}

/** The path goes in a query parameter because workspace paths contain slashes. */
export async function readConversationFile(
  conversationId: string,
  path: string,
): Promise<ConversationFileContent> {
  return apiClient.get<ConversationFileContent>(
    `/conversations/${conversationId}/workspace/file?path=${encodeURIComponent(path)}`,
  );
}
