"use client";

import { useMemo } from "react";

import { useAgents } from "@/hooks";
import type { ChatMessage, TurnUsage } from "@/types";
import { MessageItem } from "./message-item";

interface MessageListProps {
  messages: ChatMessage[];
  onRegenerate?: (messageId: string) => void;
}

/**
 * The turn whose last step stays open, or -1 when no turn did any work.
 *
 * The most recent turn that *used a tool*, which is not the most recent turn: an agent
 * that writes a file and then answers about it ends the conversation with prose, and
 * anchoring on "the newest assistant message" left the file that was just written folded
 * away. What somebody opening a conversation is looking for is the last thing the agent
 * did, wherever in the transcript that landed.
 */
export function lastToolTurnIndex(messages: ChatMessage[]): number {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (message === undefined || message.role !== "assistant") continue;
    const usedATool =
      (message.parts ?? []).some((part) => part.type === "tool" && part.toolCall) ||
      (message.toolCalls?.length ?? 0) > 0;
    if (usedATool) return index;
  }
  return -1;
}

/**
 * Whether this message continues the turn above it rather than starting one.
 *
 * One run can leave several assistant messages. It parks on an approval, somebody
 * decides, it runs again - and each segment is written as it happens, because
 * folding it back into the message before it would rewrite a turn somebody has
 * already read. That is right for the transcript and wrong on screen: one run
 * drew three avatars and three agent names down the page, which reads as three
 * agents answering one question.
 *
 * So consecutive assistant messages of the same run are drawn as one turn - the
 * avatar and the name once, at the top. Consecutive is part of the rule, not an
 * optimisation: a user message between two segments means the person said
 * something in between, and the turn genuinely restarts there.
 *
 * Two ids answer "same turn", and both are needed. `runId` is the stored one,
 * which every row of a reloaded transcript carries. A turn still streaming has
 * none - the row does not exist yet - and the client stamps `groupId` instead,
 * cleared when the turn ends. Grouping on `runId` alone therefore worked after a
 * reload and never while anybody was watching it happen, which is when a run that
 * segments looks like three agents answering: measured on a four-segment turn,
 * 32px of padding between each pair and an avatar on every one.
 *
 * The stored id wins where both have it. Neither recorded never groups: it is
 * "not recorded", not "its own run", and guessing from adjacency would fold two
 * unrelated answers into one turn.
 */
export function continuesTurn(messages: ChatMessage[], index: number): boolean {
  const message = messages[index];
  const previous = messages[index - 1];
  if (message === undefined || previous === undefined) return false;
  if (message.role !== "assistant" || previous.role !== "assistant") return false;
  if (message.runId !== undefined && previous.runId !== undefined) {
    return message.runId === previous.runId;
  }
  return message.groupId !== undefined && message.groupId === previous.groupId;
}

/** Whether the turn ends here, so the time and the cost belong under this message. */
export function endsTurn(messages: ChatMessage[], index: number): boolean {
  return !continuesTurn(messages, index + 1);
}

/**
 * What the turn cost, wherever in it that was recorded.
 *
 * The figure belongs to the turn and not to the segment that happened to carry
 * it: a run reports what it has spent when it parks, which is the *first*
 * segment, so a footer drawn from the message it sits on put the tokens and the
 * cost in the middle of the answer with nothing under the end of it.
 *
 * The last segment that recorded anything wins, because each figure is the run's
 * total as at that point rather than that segment's own share - summing them
 * would count the first segment twice.
 */
export function turnUsage(messages: ChatMessage[], index: number): TurnUsage | undefined {
  // The walk cannot run off the start: `continuesTurn` is false at index 0, which
  // is what stops it, so no bound is needed and none is written - a guard that
  // cannot fail is a line no test can reach.
  let at = index;
  while (messages[at]?.usage === undefined && continuesTurn(messages, at)) at--;
  return messages[at]?.usage;
}

export function MessageList({ messages, onRegenerate }: MessageListProps) {
  // Agents are resolved here rather than stamped onto the message, so a renamed
  // agent is labelled by its current name and a new picture appears on old
  // turns. The query is the one the agent picker already made, so this costs a
  // cache read. Archived agents are included: a conversation that an agent took
  // part in before it was retired still has to say who answered.
  const { agents } = useAgents({ includeArchived: true });
  const byId = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);

  const getGroupPosition = (
    message: ChatMessage,
  ): "first" | "middle" | "last" | "single" | undefined => {
    if (!message.groupId) return undefined;

    const groupMessages = messages.filter((m) => m.groupId === message.groupId);
    if (groupMessages.length <= 1) return "single";

    const groupIndex = groupMessages.findIndex((m) => m.id === message.id);
    if (groupIndex === 0) return "first";
    if (groupIndex === groupMessages.length - 1) return "last";
    return "middle";
  };

  // Only allow regenerating the most recent assistant message - older ones
  // would diverge the transcript in a confusing way.
  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.role === "assistant") return i;
    }
    return -1;
  })();
  const openStepsAt = lastToolTurnIndex(messages);

  return (
    <div className="space-y-0">
      {messages.map((message, index) => (
        <MessageItem
          key={message.id}
          message={message}
          agent={message.agentId ? byId.get(message.agentId) : undefined}
          groupPosition={getGroupPosition(message)}
          continuesTurn={continuesTurn(messages, index)}
          endsTurn={endsTurn(messages, index)}
          turnUsage={turnUsage(messages, index)}
          openLastStep={index === openStepsAt}
          onRegenerate={
            onRegenerate && index === lastAssistantIndex && !message.isStreaming
              ? () => onRegenerate(message.id)
              : undefined
          }
        />
      ))}
    </div>
  );
}
