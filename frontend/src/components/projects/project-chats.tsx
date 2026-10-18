"use client";

import { useMemo } from "react";
import Link from "next/link";
import { MessageSquare, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ConversationAgents } from "@/components/agents/conversation-agents";
import { RunningFor } from "@/components/chat/conversation-sidebar";
import { PersonFace } from "@/components/chat/person-face";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, DataTable, ListCard, ListCardEmpty, type Column } from "@/components/ui";
import { useProjectChats } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import { cn, timeAgo } from "@/lib/utils";
import type { ProjectChat } from "@/types";
import type { Project } from "@/types/projects";

/**
 * The project's chats as a table, and a new one.
 *
 * Everybody's, not the reader's alone: a project's chats are its members', so
 * each row says whose it is, which agents answer in it, when it last moved or
 * who is at work in it, and who has seen it - the columns a shared list is
 * scanned by, as the console's other lists are.
 */
export function ProjectChats({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const { chats, total, isLoading, error, hasMore, loadingMore, loadMore } = useProjectChats(
    project.id,
  );
  const columns = useChatColumns();
  const router = useRouter();

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
          <DataTable<ProjectChat>
            columns={columns}
            rows={chats}
            getRowKey={(chat) => chat.id}
            onRowClick={(chat) => router.push(`${ROUTES.CHAT}?id=${chat.id}`)}
          />
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

function useChatColumns(): Column<ProjectChat>[] {
  const t = useTranslations("projects");
  const tChat = useTranslations("chat");
  const tTime = useTranslations("time");
  const locale = useLocale();
  return useMemo<Column<ProjectChat>[]>(
    () => [
      {
        key: "title",
        header: t("columnChat"),
        className: "w-full max-w-0",
        sortable: true,
        sortValue: (chat) => (chat.title || "").toLowerCase(),
        cell: (chat) => (
          <Link
            href={`${ROUTES.CHAT}?id=${chat.id}`}
            className="flex min-w-0 items-center gap-2"
            onClick={(event) => event.stopPropagation()}
          >
            <span className="relative shrink-0">
              <MessageSquare className="text-muted-foreground h-4 w-4" aria-hidden />
              {chat.unread === true && (
                <span
                  role="status"
                  aria-label={tChat("sidebar.unread")}
                  className="unread-dot ring-card absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full ring-2"
                />
              )}
            </span>
            <span
              className={cn(
                "truncate",
                chat.unread === true ? "text-foreground font-semibold" : "font-medium",
              )}
            >
              {chat.title || t("untitledChat")}
            </span>
          </Link>
        ),
      },
      {
        key: "owner",
        header: t("columnStartedBy"),
        hideBelow: "md",
        className: "whitespace-nowrap",
        sortable: true,
        sortValue: (chat) => chat.owner?.name.toLowerCase() ?? null,
        cell: (chat) =>
          chat.owner ? (
            <span className="flex items-center gap-2">
              <PersonFace person={chat.owner} className="h-5 w-5 shrink-0 text-[8px]" />
              <span className="truncate">{chat.owner.name}</span>
            </span>
          ) : null,
      },
      {
        key: "agents",
        header: t("columnAgents"),
        hideBelow: "lg",
        className: "whitespace-nowrap",
        cell: (chat) =>
          (chat.agents ?? []).length > 0 ? <ConversationAgents agents={chat.agents ?? []} /> : null,
      },
      {
        key: "activity",
        header: t("columnActivity"),
        className: "whitespace-nowrap",
        sortable: true,
        sortValue: (chat) => new Date(chat.updated_at ?? chat.created_at).getTime(),
        cell: (chat) =>
          chat.working ? (
            // Who is at work in it, before how long: in a shared project the
            // question is whether somebody is already on it.
            <span className="flex items-center gap-1.5">
              <PersonFace person={chat.working} className="h-4 w-4 shrink-0 text-[7px]" />
              <span className="text-foreground">{t("isWorking", { name: chat.working.name })}</span>
              {chat.running_since && (
                <span className="text-muted-foreground">
                  · <RunningFor since={chat.running_since} />
                </span>
              )}
            </span>
          ) : (
            <span className="text-muted-foreground">
              {timeAgo(chat.updated_at ?? chat.created_at, tTime, locale)}
            </span>
          ),
      },
      {
        key: "people",
        header: t("columnPeople"),
        hideBelow: "sm",
        align: "right",
        cell: (chat) => <SeenBy readers={chat.seen_by} here={chat.here} />,
      },
    ],
    [t, tChat, tTime, locale],
  );
}

/** Faces shown before the rest of the people fold into a count. */
const FACES = 3;

/**
 * Who is in the chat now and who has had it open: the people here first, each
 * with a live dot, then the latest readers as overlapping faces, the rest as a
 * count, and every name in the tooltip - the way a shared document says who has
 * it open and who has looked at it.
 */
function SeenBy({ readers, here }: { readers: ProjectChat["seen_by"]; here: ProjectChat["here"] }) {
  const t = useTranslations("projects");
  const present = new Set(here.map((person) => person.user_id));
  const people = [...here, ...readers.filter((reader) => !present.has(reader.user_id))];
  if (people.length === 0) return null;
  const label = [
    here.length > 0 && t("hereNow", { names: here.map((person) => person.name).join(", ") }),
    readers.length > 0 && t("seenBy", { names: readers.map((reader) => reader.name).join(", ") }),
  ]
    .filter(Boolean)
    .join("\n");
  const shown = people.slice(0, FACES);
  const more = people.length - shown.length;
  return (
    <span className="flex shrink-0 items-center" title={label} aria-label={label} role="img">
      {shown.map((person, index) => (
        // The first face on top, so the live dot at its corner is not under the next.
        <span
          key={person.user_id}
          className={cn("relative", index > 0 && "-ml-1.5")}
          style={{ zIndex: shown.length - index }}
        >
          <PersonFace person={person} className="ring-card h-5 w-5 text-[8px] ring-2" />
          {present.has(person.user_id) && (
            <span className="bg-success ring-card absolute -right-px -bottom-px h-2 w-2 rounded-full ring-2" />
          )}
        </span>
      ))}
      {more > 0 && (
        <span className="bg-muted text-muted-foreground ring-card -ml-1.5 grid h-5 min-w-5 place-items-center rounded-full px-1 text-[9px] font-medium ring-2">
          {t("moreReaders", { count: more })}
        </span>
      )}
    </span>
  );
}
