import type { TaskStatus } from "@/lib/tasks-api";

export interface RoomAgentPin {
  agent_id: string;
  version_id: string;
  name: string;
  /** A version notice, not a permission. Actions use the server's can_* fields. */
  current: boolean;
}

export interface RoomLeadPolicy {
  enabled: boolean;
  revision: number;
  lead: RoomAgentPin | null;
  specialists: RoomAgentPin[];
  max_items: number;
  can_edit: boolean;
  can_ask: boolean;
}

export interface RoomLeadPolicyWrite {
  expected_revision: number;
  enabled: boolean;
  lead_agent_id: string | null;
  specialist_agent_ids: string[];
  max_items: number;
}

export interface RoomProposalItem {
  proposal_item_id: string;
  title: string;
  expected_result: string;
  accountable_user_id: string | null;
  accountable_user_name?: string | null;
  due_at: string | null;
  agent: RoomAgentPin | null;
  existing_task_id: string | null;
  expected_task_revision: number | null;
}

export interface RoomRoutingProposal {
  id: string;
  conversation_id: string;
  thread_root_message_id: string | null;
  submission_id: string;
  message_id: string;
  requester_id: string;
  lead_run_id: string | null;
  policy_revision: number;
  revision: number;
  decision: "pending" | "accepted" | "discarded";
  items: RoomProposalItem[];
  accepted_item_ids: string[];
  can_accept: boolean;
  can_discard: boolean;
  created_at: string;
}

export interface RoomProposalDecision {
  expected_revision: number;
  idempotency_key: string;
  selected_item_ids?: string[];
}

/** Browser-only pending decision. Never persisted or reused by another audience. */
export interface RoomDecisionAttempt {
  decision: "accept" | "discard";
  input: RoomProposalDecision;
}

export interface RoomTaskCard {
  id: string;
  proposal_id: string;
  proposal_item_id: string;
  message_id: string;
  thread_root_message_id: string | null;
  task_id: string;
  table_id: string;
  accepted_revision: number;
  revision: number;
  title: string;
  description: string;
  status: TaskStatus;
  next_actor: "user" | "agent";
  accountable_user_id: string | null;
  accountable_user_name?: string | null;
  agent: RoomAgentPin | null;
  due_at: string | null;
}

export interface RoomRoutingPage<T> {
  items: T[];
  has_more: boolean;
}
