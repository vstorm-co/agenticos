"use client";

import { useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { MessagesSquare, Paperclip, Send, X } from "lucide-react";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useAgentMessages, useReactToAgentMessage, useSendAgentMessage } from "@/hooks";
import { useAgents } from "@/hooks/use-agents";
import { agentMessageAttachmentUrl, MAX_MESSAGE_CHARS } from "@/lib/agent-messages-api";
import { cn, formatBytes, timeAgo } from "@/lib/utils";
import type {
  AgentMessageReactionRead,
  AgentMessageRead,
  AgentMessageThreadRead,
  AgentRef,
} from "@/types/agent-messages";

/* i18n-exempt: emoji, not copy — the reaction itself, read by code */
const REACTION_EMOJIS = ["👍", "❤️", "🎉", "👀", "✅", "🙏"] as const;

/** One emoji's count, and whether the sending agent put it there. */
function groupReactions(
  reactions: AgentMessageReactionRead[],
  mineAgentId: string | null,
): { emoji: string; count: number; mine: boolean }[] {
  const grouped = new Map<string, { count: number; mine: boolean }>();
  for (const reaction of reactions) {
    const entry = grouped.get(reaction.emoji) ?? { count: 0, mine: false };
    entry.count += 1;
    if (mineAgentId !== null && reaction.reactor_agent_id === mineAgentId) entry.mine = true;
    grouped.set(reaction.emoji, entry);
  }
  return [...grouped.entries()].map(([emoji, entry]) => ({ emoji, ...entry }));
}

/**
 * One thread, oldest first: who sent what and when, the message each one
 * answers, the reactions under it, and the files riding along — with the
 * reply box underneath, sending as one of the thread's agents.
 */
export function MessageThread({ thread }: { thread: AgentMessageThreadRead }) {
  const t = useTranslations("agentMessages");
  const ts = useTranslations("common");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { messages, isLoading, error, refetch } = useAgentMessages(thread.id);
  const { react } = useReactToAgentMessage();
  const { send } = useSendAgentMessage();
  const { agents, isLoading: isLoadingAgents, error: agentsError } = useAgents();

  const [replyTo, setReplyTo] = useState<AgentMessageRead | null>(null);
  const [body, setBody] = useState("");
  const [senderId, setSenderId] = useState<string | null>(null);

  // The sender is one of the thread's own agents the caller may run — the
  // chat picker's list, narrowed to this pair. While it loads the box waits;
  // if the list itself was refused, both agents are offered and the backend
  // refuses honestly rather than the page guessing who may send.
  const runnable = useMemo(
    () =>
      agents.filter(
        (agent) =>
          agent.can_run && (agent.id === thread.agent_a.id || agent.id === thread.agent_b.id),
      ),
    [agents, thread.agent_a.id, thread.agent_b.id],
  );
  const senderOptions: AgentRef[] =
    runnable.length > 0 ? runnable : agentsError ? [thread.agent_a, thread.agent_b] : [];
  const sender = senderId ?? senderOptions[0]?.id ?? null;
  const otherAgent = (agentId: string): AgentRef =>
    agentId === thread.agent_a.id ? thread.agent_b : thread.agent_a;

  // Fire-and-forget: nothing here needs the outcome, but an unhandled
  // rejection (a dropped connection, a reaction the backend refused) must
  // not reach the console as one — the hook already toasts the refusal.
  const toggleReaction = (message: AgentMessageRead, emoji: string) => {
    react
      .mutateAsync({
        threadId: thread.id,
        messageId: message.id,
        emoji,
        asAgentId: sender,
      })
      .catch(() => {});
  };

  const handleSend = async () => {
    if (sender === null || body.trim() === "") return;
    try {
      await send.mutateAsync({
        sender_agent_id: sender,
        recipient: otherAgent(sender).id,
        body: body.trim(),
        reply_to_message_id: replyTo?.id ?? null,
      });
    } catch {
      // The send hook already toasted the refusal with the backend's words.
      return;
    }
    setBody("");
    setReplyTo(null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-border border-b px-4 py-3">
        <h2 className="truncate text-sm font-semibold">
          {t("threadTitle", { first: thread.agent_a.name, second: thread.agent_b.name })}
        </h2>
        <p className="text-muted-foreground truncate text-xs">
          {thread.agent_a.slug} · {thread.agent_b.slug}
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {isLoading ? (
          <LoadingState variant="skeleton-list" rows={3} />
        ) : error ? (
          <ErrorState
            description={error}
            cta={{ label: ts("retry"), onClick: () => void refetch() }}
          />
        ) : messages.length === 0 ? (
          <ListCardEmpty
            icon={MessagesSquare}
            title={t("emptyMessages.title")}
            description={t("emptyMessages.description")}
          />
        ) : (
          <ul className="space-y-4">
            {messages.map((message) => {
              const answered = message.reply_to_message_id
                ? (messages.find((item) => item.id === message.reply_to_message_id) ?? null)
                : null;
              return (
                <li key={message.id}>
                  {answered ? (
                    <p className="text-muted-foreground mb-1 truncate border-l-2 pl-2 text-xs">
                      {t("replyTo", { slug: answered.sender_agent_slug })} · {answered.body}
                    </p>
                  ) : null}
                  <p className="text-sm">
                    <span className="font-medium">{message.sender_agent_slug}</span>{" "}
                    <span className="text-muted-foreground text-xs">
                      {timeAgo(message.created_at, tTime, locale)}
                    </span>
                  </p>
                  <p className="mt-0.5 text-sm break-words whitespace-pre-wrap">{message.body}</p>
                  {message.attachments.length > 0 ? (
                    <ul className="mt-1.5 flex flex-wrap gap-1.5">
                      {message.attachments.map((file) => (
                        <li key={file.chat_file_id}>
                          <a
                            href={agentMessageAttachmentUrl(
                              thread.id,
                              message.id,
                              file.chat_file_id,
                            )}
                            className="bg-muted hover:bg-muted/60 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs"
                          >
                            <Paperclip className="size-3.5 shrink-0" aria-hidden />
                            <span className="max-w-48 truncate">{file.filename}</span>
                            <span className="text-muted-foreground shrink-0">
                              {formatBytes(file.size)}
                            </span>
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">
                    {groupReactions(message.reactions, sender).map((group) => (
                      <button
                        key={group.emoji}
                        type="button"
                        aria-pressed={group.mine}
                        aria-label={t("reactWith", { emoji: group.emoji })}
                        onClick={() => toggleReaction(message, group.emoji)}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs",
                          group.mine
                            ? "border-primary bg-primary/10"
                            : "border-border hover:bg-muted/60",
                        )}
                      >
                        <span aria-hidden>{group.emoji}</span>
                        <span>{group.count}</span>
                      </button>
                    ))}
                    {REACTION_EMOJIS.filter(
                      (emoji) => !message.reactions.some((item) => item.emoji === emoji),
                    ).map((emoji) => (
                      <button
                        key={emoji}
                        type="button"
                        aria-label={t("reactWith", { emoji })}
                        onClick={() => toggleReaction(message, emoji)}
                        className="hover:bg-muted/60 inline-flex items-center rounded-full border border-transparent px-1.5 py-0.5 text-xs opacity-60 hover:opacity-100"
                      >
                        <span aria-hidden>{emoji}</span>
                      </button>
                    ))}
                    <button
                      type="button"
                      onClick={() => setReplyTo(message)}
                      className="text-muted-foreground hover:text-foreground ml-1 text-xs"
                    >
                      {t("reply")}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-border border-t px-4 py-3">
        {replyTo ? (
          <p className="text-muted-foreground mb-2 flex items-center gap-2 text-xs">
            <span className="min-w-0 flex-1 truncate">
              {t("replyTo", { slug: replyTo.sender_agent_slug })} · {replyTo.body}
            </span>
            <button
              type="button"
              aria-label={t("cancelReply")}
              onClick={() => setReplyTo(null)}
              className="hover:text-foreground shrink-0"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </p>
        ) : null}
        {isLoadingAgents ? (
          <LoadingState variant="skeleton-list" rows={1} />
        ) : senderOptions.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("noRunnableAgent")}</p>
        ) : (
          <div className="flex flex-col gap-2">
            <div className="flex gap-2">
              <Select value={sender ?? undefined} onValueChange={setSenderId}>
                <SelectTrigger aria-label={t("senderLabel")} className="w-56 shrink-0">
                  <SelectValue placeholder={t("chooseSender")} />
                </SelectTrigger>
                <SelectContent>
                  {senderOptions.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      <span>{agent.name}</span>{" "}
                      <span className="text-muted-foreground">{`@${agent.slug}`}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Textarea
                value={body}
                onChange={(event) => setBody(event.target.value.slice(0, MAX_MESSAGE_CHARS))}
                placeholder={t("replyPlaceholder")}
                aria-label={t("bodyLabel")}
                rows={2}
                className="min-h-0 flex-1 resize-none"
              />
              <Button
                onClick={() => void handleSend()}
                disabled={sender === null || body.trim() === "" || send.isPending}
                aria-label={t("send")}
              >
                <Send className="size-4" aria-hidden />
              </Button>
            </div>
            <p className="text-muted-foreground text-right text-xs">
              {t("charCount", { count: body.length, max: MAX_MESSAGE_CHARS })}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
