/**
 * Agent-to-agent messages: the shapes the console sends through the BFF proxy
 * to the backend's agent-message routes. They mirror
 * `backend/app/schemas/agent_message.py` exactly — ids are UUID strings on
 * the wire, and `last_message.body` is the first 200 characters.
 */

export interface AgentRef {
  id: string;
  slug: string;
  name: string;
}

export interface AgentMessagePreview {
  sender_agent_slug: string;
  body: string;
  created_at: string;
}

export interface AgentMessageThreadRead {
  id: string;
  agent_a: AgentRef;
  agent_b: AgentRef;
  last_message_at: string | null;
  last_message: AgentMessagePreview | null;
  unread: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentMessageThreadList {
  items: AgentMessageThreadRead[];
  total: number;
}

export interface AgentMessageRecipientList {
  items: AgentRef[];
  total: number;
}

export interface AgentMessageReactionRead {
  emoji: string;
  reactor_agent_id: string | null;
  reactor_agent_slug: string | null;
  reactor_user_id: string | null;
  created_at: string;
}

export interface AgentMessageAttachmentRead {
  chat_file_id: string;
  filename: string;
  mime_type: string;
  size: number;
  file_type: string;
}

export interface AgentMessageRead {
  id: string;
  thread_id: string;
  sender_agent_id: string;
  sender_agent_slug: string;
  sender_user_id: string | null;
  body: string;
  reply_to_message_id: string | null;
  reactions: AgentMessageReactionRead[];
  attachments: AgentMessageAttachmentRead[];
  created_at: string;
  updated_at: string;
}

export interface AgentMessageList {
  items: AgentMessageRead[];
  total: number;
}

export interface AgentMessageReactionsRead {
  reacted: boolean;
  reactions: AgentMessageReactionRead[];
}

/** What sending a message takes: the sending agent, the other agent by slug or id. */
export interface AgentMessageSend {
  sender_agent_id: string;
  recipient: string;
  body: string;
  reply_to_message_id?: string | null;
  attachment_file_ids?: string[];
}
