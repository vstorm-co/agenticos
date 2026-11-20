/**
 * API client for agent-to-agent messages: the threads between two agents,
 * the messages in one thread, and the reactions on them.
 *
 * A message is stored, never delivered as a run: the recipient reads it in
 * the console, or through its messaging tools on its next run. Sending needs
 * the caller to be able to run both agents; the backend enforces that and
 * answers 403 otherwise, which the caller surfaces as-is.
 */

import { apiClient } from "./api-client";
import type {
  AgentMessageList,
  AgentMessageRead,
  AgentMessageReactionsRead,
  AgentMessageRecipientList,
  AgentMessageSend,
  AgentMessageThreadList,
  AgentMessageThreadRead,
} from "@/types/agent-messages";

const ROOT = "/agent-messages";

/** The longest message the console sends — the backend's `MAX_BODY_CHARS`. */
export const MAX_MESSAGE_CHARS = 16_000;

/** Files on one message — the backend's `MAX_ATTACHMENTS`. */
export const MAX_ATTACHMENTS = 10;

function pageParams(skip: number, limit: number): Record<string, string> {
  return { skip: String(skip), limit: String(limit) };
}

/** The threads involving an agent this caller may run, most recently active first. */
export async function listAgentMessageThreads(
  skip = 0,
  limit = 50,
): Promise<AgentMessageThreadList> {
  return apiClient.get<AgentMessageThreadList>(ROOT, { params: pageParams(skip, limit) });
}

/** Send a message as one agent to another, in the thread the two of them share. */
export async function sendAgentMessage(input: AgentMessageSend): Promise<AgentMessageRead> {
  return apiClient.post<AgentMessageRead>(ROOT, input);
}

/** The agents this caller may message, most recent first. */
export async function listAgentMessageRecipients(
  skip = 0,
  limit = 100,
): Promise<AgentMessageRecipientList> {
  return apiClient.get<AgentMessageRecipientList>(`${ROOT}/recipients`, {
    params: pageParams(skip, limit),
  });
}

/** One thread: its two agents, its last message, and whether it waits on the reader. */
export async function getAgentMessageThread(threadId: string): Promise<AgentMessageThreadRead> {
  return apiClient.get<AgentMessageThreadRead>(`${ROOT}/${threadId}`);
}

/** One thread's messages, oldest first. */
export async function listAgentMessages(
  threadId: string,
  skip = 0,
  limit = 50,
): Promise<AgentMessageList> {
  return apiClient.get<AgentMessageList>(`${ROOT}/${threadId}/messages`, {
    params: pageParams(skip, limit),
  });
}

/** Mark a thread read. The backend answers 204 with no body. */
export async function markAgentMessageThreadRead(threadId: string): Promise<void> {
  await apiClient.post<void>(`${ROOT}/${threadId}/read`, undefined);
}

/**
 * React to a message, or take the reaction back by sending it again.
 *
 * `asAgentId` reacts as that agent in the thread; omitted, the reaction is
 * the reader's own.
 */
export async function reactToAgentMessage(
  threadId: string,
  messageId: string,
  emoji: string,
  asAgentId?: string | null,
): Promise<AgentMessageReactionsRead> {
  return apiClient.post<AgentMessageReactionsRead>(
    `${ROOT}/${threadId}/messages/${messageId}/reactions`,
    { emoji, as_agent_id: asAgentId ?? null },
  );
}

/**
 * Where a message's attachment is read from, as a link rather than a fetch:
 * the BFF proxies the bytes, so the browser follows the link and the file
 * downloads (or renders inline) without the bytes ever entering JavaScript.
 */
export function agentMessageAttachmentUrl(
  threadId: string,
  messageId: string,
  fileId: string,
): string {
  return `/api${ROOT}/${threadId}/messages/${messageId}/attachments/${fileId}?disposition=inline`;
}
