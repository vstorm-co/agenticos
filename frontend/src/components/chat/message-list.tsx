"use client";

import { Fragment, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { useAgents } from "@/hooks";
import { consoleLink, pointAt } from "@/lib/assistant-highlight";
import { dayLabel, startsADay } from "@/lib/day-separator";
import type { ChatMessage, TurnUsage } from "@/types";
import type { PinnedPrompts } from "./chat-container";
import { MessageItem } from "./message-item";

interface MessageListProps {
  messages: ChatMessage[];
  onRegenerate?: (messageId: string) => void;
  /** The test panel's pinned questions; a question here can be pinned or taken off. */
  pins?: PinnedPrompts;
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

interface MessageLayout {
  message: ChatMessage;
  groupPosition?: "first" | "middle" | "last" | "single";
  continuesTurn: boolean;
  endsTurn: boolean;
  turnUsage?: TurnUsage;
  request?: string;
}

/** Prepare transcript-wide relationships once per update, in linear time.
 * Usage is a run's latest cumulative figure, and the nearest user message owns
 * the request even when it contains only a file. Group positions also include
 * nonadjacent segments, while turn continuation still requires adjacency.
 */
export function layoutMessages(messages: ChatMessage[]): MessageLayout[] {
  const groups = new Map<string, number[]>();
  messages.forEach((message, index) => {
    if (!message.groupId) return;
    const indices = groups.get(message.groupId);
    if (indices) indices.push(index);
    else groups.set(message.groupId, [index]);
  });
  const positions = new Map<number, MessageLayout["groupPosition"]>();
  groups.forEach((indices) => {
    indices.forEach((index, position) => {
      positions.set(
        index,
        indices.length === 1
          ? "single"
          : position === 0
            ? "first"
            : position === indices.length - 1
              ? "last"
              : "middle",
      );
    });
  });
  let usage: TurnUsage | undefined;
  let request: string | undefined;
  return messages.map((message, index) => {
    const continues = continuesTurn(messages, index);
    const ends = endsTurn(messages, index);
    usage = message.usage ?? (continues ? usage : undefined);
    if (message.role === "user") request = message.content || undefined;
    return {
      message,
      groupPosition: positions.get(index),
      continuesTurn: continues,
      endsTurn: ends,
      turnUsage: usage,
      request: message.role === "assistant" && ends ? request : undefined,
    };
  });
}

export function MessageList({ messages, onRegenerate, pins }: MessageListProps) {
  // Agents are resolved here rather than stamped onto the message, so a renamed
  // agent is labelled by its current name and a new picture appears on old
  // turns. The query is the one the agent picker already made, so this costs a
  // cache read. Archived agents are included: a conversation that an agent took
  // part in before it was retired still has to say who answered.
  const { agents } = useAgents({ includeArchived: true });
  const byId = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);
  const router = useRouter();

  const layout = useMemo(() => layoutMessages(messages), [messages]);

  // Only allow regenerating the most recent assistant message - older ones
  // would diverge the transcript in a confusing way.
  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.role === "assistant") return i;
    }
    return -1;
  })();
  const lastAssistantId = messages[lastAssistantIndex]?.id;
  const regenerateLast = useMemo(() => {
    if (onRegenerate === undefined || lastAssistantId === undefined) return undefined;
    return () => onRegenerate(lastAssistantId);
  }, [onRegenerate, lastAssistantId]);
  const openStepsAt = lastToolTurnIndex(messages);
  const timestamps = messages.map((message) => message.timestamp);
  const now = new Date();

  // "Show me" (#2301): a console link an agent wrote opens that page in the
  // console and points at the control its `?highlight=` names, as the
  // Architect's links do - rather than reloading the whole app.
  const onClickCapture = (event: React.MouseEvent) => {
    const anchor = (event.target as Element).closest("a");
    const link = consoleLink(anchor?.getAttribute("href") ?? null, window.location.origin);
    if (link === null) return;
    event.preventDefault();
    router.push(link.path);
    if (link.anchor) void pointAt(link.anchor);
  };

  return (
    <div className="space-y-0" onClickCapture={onClickCapture}>
      {layout.map(({ message, ...row }, index) => (
        <Fragment key={message.renderKey ?? message.id}>
          {/* Never inside a turn: a run that crossed midnight is still one answer. */}
          {!row.continuesTurn && startsADay(timestamps, index, now) && (
            <DaySeparator at={message.timestamp} now={now} />
          )}
          <MessageItem
            message={message}
            agent={message.agentId ? byId.get(message.agentId) : undefined}
            groupPosition={row.groupPosition}
            continuesTurn={row.continuesTurn}
            endsTurn={row.endsTurn}
            turnUsage={row.turnUsage}
            openLastStep={index === openStepsAt}
            pins={pins}
            agents={agents}
            request={pins ? undefined : row.request}
            onRegenerate={
              onRegenerate && index === lastAssistantIndex && !message.isStreaming
                ? regenerateLast
                : undefined
            }
          />
        </Fragment>
      ))}
    </div>
  );
}

/** Where the transcript crosses into another day: a small pill, centred. */
function DaySeparator({ at, now }: { at: Date; now: Date }) {
  const t = useTranslations("chat.days");
  const locale = useLocale();
  return (
    <div role="separator" className="flex justify-center py-4">
      <span className="bg-foreground/[0.06] text-muted-foreground rounded-full px-3 py-1 text-xs font-medium">
        {dayLabel(at, now, locale, t)}
      </span>
    </div>
  );
}
