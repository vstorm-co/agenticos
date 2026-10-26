import type { ChatMessage, ToolCall } from "@/types/chat";

export interface NextStepEvent {
  conversation_id: string;
  message_id: string;
  steps: string[];
}

export function nextStepEvent(data: unknown): NextStepEvent | null {
  if (
    typeof data !== "object" ||
    data === null ||
    !("conversation_id" in data) ||
    typeof data.conversation_id !== "string" ||
    !("message_id" in data) ||
    typeof data.message_id !== "string" ||
    !("steps" in data) ||
    !Array.isArray(data.steps) ||
    data.steps.length > 3
  )
    return null;
  const steps: string[] = [];
  for (const step of data.steps) {
    if (typeof step !== "string" || !step.trim() || step.length > 80) return null;
    steps.push(step);
  }
  if (!data.conversation_id || !data.message_id) return null;
  return { conversation_id: data.conversation_id, message_id: data.message_id, steps };
}

export function withNextSteps(message: ChatMessage, event: NextStepEvent): ChatMessage {
  if (
    event.steps.length === 0 ||
    message.role !== "assistant" ||
    message.id !== event.message_id ||
    message.conversationId !== event.conversation_id
  )
    return message;
  const id = `next_steps_${event.message_id}`;
  if (message.toolCalls?.some((call) => call.id === id)) return message;
  const call: ToolCall = {
    id,
    name: "suggest_next_steps",
    args: { steps: event.steps },
    result: JSON.stringify({ steps: event.steps }),
    status: "completed",
  };
  return {
    ...message,
    toolCalls: [...(message.toolCalls ?? []), call],
    parts: message.parts ? [...message.parts, { id, type: "tool", toolCall: call }] : undefined,
  };
}

/** A transcript read that started before the optional buttons were saved is stale. */
export function retainNextSteps(incoming: ChatMessage, local: ChatMessage): ChatMessage {
  let message = incoming;
  for (const call of local.toolCalls ?? []) {
    if (
      call.name !== "suggest_next_steps" ||
      call.id !== `next_steps_${local.id}` ||
      call.status !== "completed"
    )
      continue;
    const event = nextStepEvent({
      conversation_id: local.conversationId,
      message_id: local.id,
      steps: call.args.steps,
    });
    if (event) message = withNextSteps(message, event);
  }
  return message;
}
