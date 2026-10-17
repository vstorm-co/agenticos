"use client";

import Link from "next/link";
import { MessageSquare, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ConversationAgents } from "@/components/agents/conversation-agents";
import { RunningFor } from "@/components/chat/conversation-sidebar";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useProjectChats } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn, timeAgo } from "@/lib/utils";
import type { Conversation } from "@/types";
import type { Project } from "@/types/projects";

/**
 * The project's chats, drawn as the chat list draws them, and a new one.
 *
 * The same row as `/chat`'s sidebar - who the thread is with, when it last
 * moved or that it is at work, over its title, and the unread mark - so a chat
 * found here is recognised there.
 */
export function ProjectChats({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const { chats, total, isLoading, error } = useProjectChats(project.id);

  const newChat = project.can_use ? (
    <Button asChild size="sm">
      <Link href={ROUTES.PROJECT_CHAT(project.id)} data-tour="project-new-chat">
        <Plus className="h-4 w-4" />
        {t("newChat")}
      </Link>
    </Button>
  ) : undefined;

  return (
    <ListCard
      title={t("chats")}
      counted={error ? null : t("chatCount", { count: total })}
      controls={newChat}
      empty={!isLoading && !error && total === 0}
    >
      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : chats.length === 0 ? (
        <ListCardEmpty
          icon={MessageSquare}
          title={t("noChatsYet")}
          description={project.can_use ? t("noChatsHint") : t("noChatsViewer")}
        />
      ) : (
        <ul className="grid grid-cols-1 gap-1 p-2 md:grid-cols-2">
          {chats.map((chat) => (
            <li key={chat.id}>
              <ChatRow chat={chat} />
            </li>
          ))}
        </ul>
      )}
    </ListCard>
  );
}

function ChatRow({ chat }: { chat: Conversation }) {
  const t = useTranslations("projects");
  const tChat = useTranslations("chat");
  const tTime = useTranslations("time");
  const tAgents = useTranslations("agents");
  const locale = useLocale();
  const agents = chat.agents ?? [];
  const unread = chat.unread === true;
  const agentLabel =
    agents.length === 0
      ? null
      : agents.length === 1
        ? agents[0]!.name
        : tAgents("agentCount", { count: agents.length });

  return (
    <Link
      href={`${ROUTES.CHAT}?id=${chat.id}`}
      className="hover:bg-accent/60 flex min-w-0 items-center gap-3 rounded-lg px-3 py-2"
    >
      <span className="relative shrink-0">
        {agents.length > 0 ? (
          <ConversationAgents agents={agents} showName={false} />
        ) : (
          <span className="bg-muted grid size-6 place-items-center rounded-full">
            <MessageSquare className="text-muted-foreground h-3 w-3" aria-hidden />
          </span>
        )}
        {unread && (
          <span
            role="status"
            aria-label={tChat("sidebar.unread")}
            className="unread-dot ring-background absolute -top-px -right-px h-2 w-2 rounded-full ring-2"
          />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-muted-foreground block truncate text-[11px] leading-4">
          {chat.running_since ? (
            <RunningFor since={chat.running_since} />
          ) : (
            <>
              {agentLabel && <>{agentLabel} · </>}
              {timeAgo(chat.updated_at ?? chat.created_at, tTime, locale)}
            </>
          )}
        </span>
        <span
          className={cn(
            "block truncate text-[13px] leading-[18px]",
            unread ? "text-foreground font-semibold" : "text-foreground/80 font-medium",
          )}
        >
          {chat.title || t("untitledChat")}
        </span>
      </span>
    </Link>
  );
}
