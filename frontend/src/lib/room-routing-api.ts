import { apiClient } from "@/lib/api-client";
import type {
  RoomLeadPolicy,
  RoomLeadPolicyWrite,
  RoomProposalDecision,
  RoomRoutingPage,
  RoomRoutingProposal,
  RoomTaskCard,
} from "@/types/room-routing";

const room = (id: string) => `/conversations/${id}`;
export const ROOM_ROUTING_PAGE_SIZE = 50;

export function getRoomLeadPolicy(id: string, signal?: AbortSignal) {
  return apiClient.get<RoomLeadPolicy>(`${room(id)}/lead-policy`, { signal });
}

export function putRoomLeadPolicy(id: string, input: RoomLeadPolicyWrite) {
  return apiClient.put<RoomLeadPolicy>(`${room(id)}/lead-policy`, input);
}

function pageParams(threadRoot: string | null, skip: number) {
  return {
    limit: String(ROOM_ROUTING_PAGE_SIZE),
    skip: String(skip),
    ...(threadRoot === null ? {} : { thread_root_message_id: threadRoot }),
  };
}

export function listRoomRoutingProposals(
  id: string,
  threadRoot: string | null,
  skip: number,
  signal?: AbortSignal,
) {
  return apiClient.get<RoomRoutingPage<RoomRoutingProposal>>(`${room(id)}/routing-proposals`, {
    params: pageParams(threadRoot, skip),
    signal,
  });
}

export function getRoomRoutingProposal(id: string, proposalId: string) {
  return apiClient.get<RoomRoutingProposal>(`${room(id)}/routing-proposals/${proposalId}`);
}

export function decideRoomRoutingProposal(
  id: string,
  proposalId: string,
  decision: "accept" | "discard",
  input: RoomProposalDecision,
) {
  return apiClient.post<RoomRoutingProposal>(
    `${room(id)}/routing-proposals/${proposalId}/${decision}`,
    input,
  );
}

export function listRoomTaskCards(
  id: string,
  threadRoot: string | null,
  skip: number,
  signal?: AbortSignal,
) {
  return apiClient.get<RoomRoutingPage<RoomTaskCard>>(`${room(id)}/task-links`, {
    params: pageParams(threadRoot, skip),
    signal,
  });
}
