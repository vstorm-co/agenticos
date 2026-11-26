import { apiClient } from "@/lib/api-client";

export interface WaitingChatQuestion {
  run_id: string;
  conversation_id: string;
  conversation_title: string | null;
  agent_name: string;
  expires_at: string;
}

export function listWaitingChatQuestions(skip: number) {
  return apiClient.get<{ items: WaitingChatQuestion[]; total: number }>(
    "/conversations/waiting-questions",
    { params: { skip: String(skip) } },
  );
}
