"use client";

import Link from "next/link";
import { MessageSquare, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ConversationAgents } from "@/components/agents/conversation-agents";
import { RunningFor } from "@/components/chat/conversation-sidebar";
import { PersonFace } from "@/components/chat/person-face";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useProjectChats } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn, timeAgo } from "@/lib/utils";
import type { ProjectChat } from "@/types";
import type { Project } from "@/types/projects";

/**
 * The project's chats, drawn as the chat list draws them, and a new one.
 *
 * The same row as `/chat`'s sidebar - who the thread is with, when it last
 * moved or that it is at work, over its title, and the unread mark - so a chat
 * found here is recognised there. Everybody's, not the reader's alone: a
 * project's chats are its members', so each also says whose it is, who is at
 * work in it and who has seen it.
 */
export function ProjectChats({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const { chats, total, isLoading, error, hasMore, loadingMore, loadMore } = useProjectChats(
    project.id,
  );

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
        <>
          <ul className="grid grid-cols-1 gap-1 p-2 md:grid-cols-2">
            {chats.map((chat) => (
              <li key={chat.id}>
                <ChatRow chat={chat} />
              </li>
            ))}
          </ul>
          {hasMore && (
            <div className="flex justify-center px-2 pb-3">
              <Button variant="ghost" size="sm" onClick={loadMore} disabled={loadingMore}>
                {t("moreChats")}
              </Button>
            </div>
          )}
        </>
      )}
    </ListCard>
  );
}

function ChatRow({ chat }: { chat: ProjectChat }) {
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
        <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-[11px] leading-4">
          {chat.working ? (
            // Who is at work in it, before how long: in a shared project the
            // question is whether somebody is already on it.
            <>
              <PersonFace person={chat.working} className="h-3.5 w-3.5 shrink-0 text-[7px]" />
              <span className="text-foreground/80 truncate">
                {t("isWorking", { name: chat.working.name })}
              </span>
              {chat.running_since && (
                <span className="shrink-0">
                  · <RunningFor since={chat.running_since} />
                </span>
              )}
            </>
          ) : (
            <>
              {chat.owner && (
                <span
                  className="flex min-w-0 shrink items-center gap-1"
                  title={t("startedBy", { name: chat.owner.name })}
                >
                  <PersonFace person={chat.owner} className="h-3.5 w-3.5 shrink-0 text-[7px]" />
                  <span className="truncate">{chat.owner.name}</span>
                </span>
              )}
              <span className="shrink-0 truncate">
                {chat.owner && "· "}
                {agentLabel && <>{agentLabel} · </>}
                {timeAgo(chat.updated_at ?? chat.created_at, tTime, locale)}
              </span>
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
      <SeenBy readers={chat.seen_by} />
    </Link>
  );
}

/** Faces shown before the rest of the readers fold into a count. */
const FACES = 3;

/**
 * Who has had the chat open: the latest few as overlapping faces, the rest as a
 * count, and every name in the tooltip - the way a shared document says who
 * has looked at it.
 */
function SeenBy({ readers }: { readers: ProjectChat["seen_by"] }) {
  const t = useTranslations("projects");
  if (readers.length === 0) return null;
  const names = readers.map((reader) => reader.name).join(", ");
  const shown = readers.slice(0, FACES);
  const more = readers.length - shown.length;
  return (
    <span
      className="flex shrink-0 items-center"
      title={t("seenBy", { names })}
      aria-label={t("seenBy", { names })}
      role="img"
    >
      {shown.map((reader, index) => (
        <PersonFace
          key={reader.user_id}
          person={reader}
          className={cn("ring-card h-5 w-5 text-[8px] ring-2", index > 0 && "-ml-1.5")}
        />
      ))}
      {more > 0 && (
        <span className="bg-muted text-muted-foreground ring-card -ml-1.5 grid h-5 min-w-5 place-items-center rounded-full px-1 text-[9px] font-medium ring-2">
          {t("moreReaders", { count: more })}
        </span>
      )}
    </span>
  );
}
