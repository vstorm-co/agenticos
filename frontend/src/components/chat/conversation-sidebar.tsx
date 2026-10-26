"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useAgents, useConversations } from "@/hooks";
import { ConversationSearchDialog } from "@/components/chat/conversation-search-dialog";
import { Button, Skeleton } from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { IconButton } from "@/components/ui";
import { ConversationAgents } from "@/components/agents/conversation-agents";
import { cn, setUrlParam, timeAgo } from "@/lib/utils";
import {
  useAgentSelectionStore,
  useChatBandsStore,
  useChatSidebarStore,
  useWorkingStore,
} from "@/stores";
import { DEFAULT_COLLAPSED_BANDS, LONG_LIST } from "@/stores/chat-sidebar-store";
import { useProjects } from "@/hooks/use-projects";
import {
  Archive,
  ArchiveRestore,
  Star,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  Inbox,
  Loader2,
  MessageSquare,
  MoreVertical,
  Pencil,
  Search,
  SearchX,
  Share2,
  SquarePen,
  Trash2,
} from "lucide-react";
import type { Conversation } from "@/types";
import {
  ConversationFilters,
  DEFAULT_SORT,
  isConversationSort,
  splitSort,
  type ConversationSort,
} from "./conversation-filters";
import { ShareDialog } from "./share-dialog";
import { useTurnElapsed } from "./work-fold";
import { formatElapsed } from "@/lib/elapsed";

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onArchive: () => void;
  onUnarchive: () => void;
  onRename: (title: string) => void;
  onShare: () => void;
  onFavourite: (favourite: boolean) => void;
}

/** How long a thread left mid-answer keeps its mark when the listing never shows
 *  its run: a turn that short is over by then, and the listing is right. */
const HANDOFF_GRACE_MS = 20_000;

function ConversationItem({
  conversation,
  isActive,
  onSelect,
  onDelete,
  onArchive,
  onUnarchive,
  onRename,
  onShare,
  onFavourite,
}: ConversationItemProps) {
  const t = useTranslations("chat");
  const tTime = useTranslations("time");
  const tAgents = useTranslations("agents");
  const locale = useLocale();
  const [showMenu, setShowMenu] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(conversation.title || "");

  const handleRename = () => {
    if (editTitle.trim()) {
      onRename(editTitle.trim());
    }
    setIsEditing(false);
  };

  const displayTitle = conversation.title || t("newConversation");
  const unread = conversation.unread === true && !isActive;
  // Who the thread is with. The listing names the agents its runs went to; the
  // open thread whose first run has not been listed yet is with the agent the
  // composer addressed, which the console already knows - so no row falls back
  // to a generic mark.
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents: catalog } = useAgents({ includeArchived: true });
  const addressed =
    isActive && !conversation.agents?.length
      ? catalog.find((agent) => agent.id === selectedAgentId)
      : undefined;
  const agents =
    conversation.agents?.length || !addressed
      ? (conversation.agents ?? [])
      : [
          {
            id: addressed.id,
            slug: addressed.slug,
            name: addressed.name,
            has_avatar: addressed.has_avatar ?? false,
          },
        ];
  // The server's word, or this tab's own when it is the one waiting: a short turn
  // can begin and end between two listings, and the thread asked in must not
  // look idle for it.
  const workingHere = useWorkingStore((state) => state.since[conversation.id]);
  const runningSince = conversation.running_since ?? workingHere ?? null;
  // A thread this tab left mid-answer keeps its own mark until the listing has
  // the run - then the listing speaks for it, and polls it to its end - or until
  // long enough that a turn the listing never saw has surely finished.
  const handedOff = useWorkingStore((state) => conversation.id in state.handedOff);
  const settleWorking = useWorkingStore((state) => state.settle);
  const listed = conversation.running_since != null;
  useEffect(() => {
    if (!handedOff) return;
    if (listed) {
      settleWorking(conversation.id);
      return;
    }
    const timer = setTimeout(() => settleWorking(conversation.id), HANDOFF_GRACE_MS);
    return () => clearTimeout(timer);
  }, [handedOff, listed, conversation.id, settleWorking]);
  const agentLabel =
    agents.length === 0
      ? null
      : agents.length === 1
        ? agents[0]!.name
        : tAgents("agentCount", { count: agents.length });

  return (
    <div
      className={cn(
        // The open row is a fill, as the main sidebar's is - a hairline border
        // and a bar at its edge read as two thin lines around one choice.
        "group relative flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1 transition-colors",
        isActive ? "bg-accent" : "hover:bg-accent/60",
      )}
      onClick={onSelect}
    >
      {/* Which agent the thread is with leads the row - the face people pick a
          thread by. */}
      <span className="relative shrink-0">
        {agents.length > 0 ? (
          <ConversationAgents agents={agents} showName={false} />
        ) : (
          // A box the size of a face, so every title starts at the same x.
          <span className="block size-6" aria-hidden />
        )}
        {/* An answer arrived while the reader was elsewhere: a badge on the face,
            as a count sits on an app icon - part of the row's own mark rather
            than a stray dot at its far edge. Not on the open row, which is being
            read as it arrives. */}
        {unread && (
          <span
            role="status"
            aria-label={t("sidebar.unread")}
            className="unread-dot ring-background absolute -top-px -right-px h-2 w-2 rounded-full ring-2"
          />
        )}
      </span>
      {isEditing ? (
        <input
          type="text"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleRename();
            if (e.key === "Escape") setIsEditing(false);
          }}
          className="text-foreground min-w-0 flex-1 bg-transparent text-[13px] font-medium outline-none"
          autoFocus
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        // Two lines, as a session list in a chat app reads: who the thread is
        // with and when it last moved, small, over the title it is picked by.
        // One line hid the time behind a hover and left the face to say who.
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground truncate text-[11px] leading-4">
            {/* At work, the line says so and for how long, in place of who and
                when: beside the agent's name it was cut to nothing. The face
                still says who. */}
            {runningSince ? (
              <RunningFor since={runningSince} />
            ) : (
              <>
                {agentLabel && <>{agentLabel} · </>}
                {timeAgo(conversation.updated_at || conversation.created_at, tTime, locale)}
              </>
            )}
          </p>
          <div className="flex min-w-0 items-center gap-1.5">
            {/* Medium, and semibold only while it holds something unread - the
                weight is the second half of the mark, as in a mail client. */}
            <span
              className={cn(
                "truncate text-[13px] leading-[18px]",
                unread ? "text-foreground font-semibold" : "font-medium",
                !unread && (isActive ? "text-foreground" : "text-foreground/80"),
              )}
            >
              {displayTitle}
            </span>
            {/* Opened by a script through an API key, not typed here (#2122). */}
            {conversation.origin === "api" && (
              <span className="border-border text-muted-foreground shrink-0 rounded border px-1 font-mono text-[10px] leading-4">
                {t("sidebar.apiBadge")}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="relative">
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("conversationActions")}
          className={cn(
            // Zero *width* until it is wanted, not just transparent: an
            // invisible control that still reserves 32px is 32px taken off
            // every title in the list to show something nobody is looking at.
            // The row reflows on hover and the title truncates a little
            // earlier, which is the trade the right way round.
            //
            // Width rather than `hidden`, because `hidden` takes it out of the
            // tab order: a keyboard user reaches this by tabbing, and
            // `focus-visible` is what opens it for them. `touch:` keeps it
            // permanently sized where there is no hover at all - a phone cannot
            // reveal a zero-width target, and this menu is the only way to
            // reach Rename, Share, Archive and Delete. That variant is declared
            // in `globals.css`; it was in use here and undeclared, which
            // compiled to nothing.
            "h-7 shrink-0 overflow-hidden p-0 transition-[width,opacity]",
            "w-0 opacity-0",
            "group-hover:w-7 group-hover:opacity-100",
            "focus-visible:w-7 focus-visible:opacity-100",
            "touch:w-7 touch:opacity-100",
            showMenu && "w-7 opacity-100",
          )}
          onClick={(e) => {
            e.stopPropagation();
            setShowMenu(!showMenu);
          }}
        >
          <MoreVertical className="h-4 w-4" />
        </Button>

        {showMenu && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
            {/* Drawn like every other menu in the console: one line per item,
                read from the left, as wide as its longest label. */}
            <div className="panel absolute top-8 right-0 z-20 w-max min-w-44 rounded-xl p-1 shadow-lg">
              <button
                className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  setIsEditing(true);
                  setShowMenu(false);
                }}
              >
                <Pencil className="h-4 w-4" />
                {t("rename")}
              </button>
              {/* Not for a project's chat: who reads it is the project's to say,
                  and the server refuses a share of one. */}
              {!conversation.project_id && (
                <button
                  className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    onShare();
                    setShowMenu(false);
                  }}
                >
                  <Share2 className="h-4 w-4" />
                  {t("share")}
                </button>
              )}
              {/* In the menu as well as on the row: the hover control does not
                  exist on a touch screen until something is long-pressed. */}
              <button
                className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  onFavourite(conversation.is_favourite !== true);
                  setShowMenu(false);
                }}
              >
                <Star
                  className={cn(
                    "h-4 w-4",
                    conversation.is_favourite && "text-warning fill-current",
                  )}
                />
                {conversation.is_favourite ? t("unfavourite") : t("favourite")}
              </button>
              {conversation.is_archived ? (
                <button
                  className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    onUnarchive();
                    setShowMenu(false);
                  }}
                >
                  <ArchiveRestore className="h-4 w-4" />
                  {t("restore")}
                </button>
              ) : (
                <button
                  className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    onArchive();
                    setShowMenu(false);
                  }}
                >
                  <Archive className="h-4 w-4" />
                  {t("archive")}
                </button>
              )}
              <button
                className="text-destructive hover:bg-destructive/10 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm whitespace-nowrap max-md:min-h-11 [&_svg]:shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete();
                  setShowMenu(false);
                }}
              >
                <Trash2 className="h-4 w-4" />
                {t("delete")}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

type ConversationView = "active" | "archived";

interface ConversationListProps {
  conversations: Conversation[];
  total: number;
  view: ConversationView;
  onViewChange: (view: ConversationView) => void;
  /** Whether a search or an agent is narrowing the list right now. */
  isFiltered: boolean;
  onClearFilters: () => void;
  currentConversationId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onArchive: (id: string) => void;
  onUnarchive: (id: string) => void;
  onFavourite: (id: string, favourite: boolean) => void;
  onRename: (id: string, title: string) => void;
  onNavigate?: () => void;
  onLoadMore?: () => void;
  /** Whether the list is newest-activity first, so it can be read by day. */
  datedOrder: boolean;
}

/**
 * A thread at work, in place of when it last moved: a spinner and how long the
 * run has been going, counted here between the listing's reads.
 */
export function RunningFor({ since }: { since: string }) {
  const t = useTranslations("chat.steps");
  const started = useMemo(() => new Date(since), [since]);
  const elapsed = useTurnElapsed(started, true);
  return (
    <span className="text-foreground/80 inline-flex items-center gap-1">
      <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
      {elapsed === null ? t("working") : t("workingFor", { duration: formatElapsed(elapsed, t) })}
    </span>
  );
}

/** An icon in the list's header: square, quiet until pointed at. */
const HEADER_ICON = "text-muted-foreground hover:text-foreground h-8 w-8 rounded-lg [&_svg]:size-4";

/** The bands a dated list falls into, newest first. */
const AGES = ["today", "yesterday", "week", "month", "older"] as const;
type Age = (typeof AGES)[number];

/**
 * Threads by how long ago they were last active, in the order they arrived.
 *
 * Calendar days in the reader's own time, not 24-hour windows: something from
 * last night is "Yesterday" at nine in the morning.
 */
export function byAge(
  conversations: Conversation[],
  now: Date = new Date(),
): { age: Age; rows: Conversation[] }[] {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86_400_000;
  const ageOf = (conversation: Conversation): Age => {
    const at = new Date(conversation.updated_at || conversation.created_at).getTime();
    if (at >= startOfToday) return "today";
    if (at >= startOfToday - day) return "yesterday";
    if (at >= startOfToday - 7 * day) return "week";
    if (at >= startOfToday - 30 * day) return "month";
    return "older";
  };
  const groups = new Map<Age, Conversation[]>();
  for (const conversation of conversations) {
    const age = ageOf(conversation);
    groups.set(age, [...(groups.get(age) ?? []), conversation]);
  }
  return AGES.filter((age) => groups.has(age)).map((age) => ({ age, rows: groups.get(age)! }));
}

/** A project's initial on a tile - the mark the main sidebar draws for it too. */
function ProjectTile({ name }: { name: string }) {
  return (
    <span
      aria-hidden
      className="bg-foreground/[0.07] text-foreground flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-[5px] text-[10px] leading-none font-semibold"
    >
      {name.trim().charAt(0).toUpperCase()}
    </span>
  );
}

/** One band of the list: what heads it, and the threads under it. */
interface Band {
  key: string;
  heading: string | null;
  icon: "star" | "unread" | "project" | null;
  rows: Conversation[];
}

/**
 * The threads started in a project, one band per project, in the order the list
 * reached them - so the project worked in most recently comes first.
 *
 * A project the reader can no longer see still heads its threads, under a
 * generic name: they are the reader's own chats, and hiding them would lose them.
 */
export function byProject(
  conversations: Conversation[],
  names: ReadonlyMap<string, string>,
  unnamed: string,
): { inProjects: Band[]; outside: Conversation[] } {
  const bands = new Map<string, Band>();
  const outside: Conversation[] = [];
  for (const conversation of conversations) {
    const projectId = conversation.project_id;
    if (!projectId) {
      outside.push(conversation);
      continue;
    }
    const band = bands.get(projectId) ?? {
      key: `project:${projectId}`,
      heading: names.get(projectId) ?? unnamed,
      icon: "project" as const,
      rows: [],
    };
    band.rows.push(conversation);
    bands.set(projectId, band);
  }
  return { inProjects: [...bands.values()], outside };
}

/**
 * The list, split into the starred run at the top and everything else.
 *
 * A split of what arrived rather than a filter over it: the server has
 * already put the favourites first - it has to, because the list is paged and
 * a favourite sorted into page two by recency would sit under fifty threads
 * that are not (#929) - so this reads the run off the front and heads it.
 *
 * One band, not two: the rest of the list keeps the heading it always had,
 * which is the count above it. A second "Everything else" would be a label on
 * the absence of a label.
 *
 * Not in the archived view. A star survives archiving, but the band is the
 * active list's, and a band inside the archive would be a second place to
 * look for what archiving just moved.
 */
function useBands(
  conversations: Conversation[],
  currentConversationId: string | null,
  isArchivedView: boolean,
  datedOrder: boolean,
): Band[] {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  // The names a project band is headed with. Every project the reader works in
  // fits one page; one they lost access to is headed generically by `byProject`.
  const { projects } = useProjects({ limit: 100 });
  const names = useMemo(
    () => new Map(projects.map((project) => [project.id, project.name])),
    [projects],
  );
  return useMemo((): Band[] => {
    // Threads with an answer the reader has not seen lead the list, as an inbox
    // does, and leave the band they would otherwise sit in. Not the open one,
    // which is being read, nor in the archive.
    const unread = isArchivedView
      ? []
      : conversations.filter(
          (conversation) =>
            conversation.unread === true && conversation.id !== currentConversationId,
        );
    const remaining = conversations.filter((conversation) => !unread.includes(conversation));
    const firstOther = remaining.findIndex((conversation) => conversation.is_favourite !== true);
    const starred = isArchivedView
      ? []
      : remaining.slice(0, firstOther === -1 ? remaining.length : firstOther);
    // Threads in a project sit under it rather than under their date, the way a
    // folder holds its files. Not in the archive, which is one flat list.
    const { inProjects, outside: rest } = isArchivedView
      ? { inProjects: [], outside: remaining.slice(starred.length) }
      : byProject(remaining.slice(starred.length), names, ts("unnamedProject"));
    return [
      ...(unread.length > 0
        ? [{ key: "unread", heading: ts("unreadHeading"), icon: "unread" as const, rows: unread }]
        : []),
      ...(starred.length > 0
        ? [{ key: "favourites", heading: t("favourites"), icon: "star" as const, rows: starred }]
        : []),
      ...inProjects,
      // Under the date they were last active, the way a chat product's history
      // reads, when the list is in that order; any other order has no dates to
      // fall into, so it stays one run.
      ...(datedOrder
        ? byAge(rest).map(({ age, rows }) => ({
            key: age,
            heading: ts(`age.${age}`),
            icon: null,
            rows,
          }))
        : rest.length > 0
          ? [{ key: "rest", heading: null, icon: null, rows: rest }]
          : []),
    ];
  }, [conversations, currentConversationId, isArchivedView, datedOrder, names, t, ts]);
}

/**
 * Which bands are drawn folded, and how to flip one.
 *
 * A band somebody folded or opened by hand stays that way. One nobody chose for
 * follows the default: the older bands (`DEFAULT_COLLAPSED_BANDS`) fold only on
 * a long list, and never the newest band on it - a person with nothing from the
 * last two days used to open Chats onto two folded headings and no thread.
 */
function useBandFolds(bands: Band[], loaded: number) {
  const folded = useChatBandsStore((state) => state.folded);
  const opened = useChatBandsStore((state) => state.opened);
  const toggle = useChatBandsStore((state) => state.toggle);
  const newest = bands.find((band) => band.heading !== null)?.key;
  const isFolded = (key: string): boolean => {
    if (folded.includes(key)) return true;
    if (opened.includes(key)) return false;
    return key !== newest && loaded > LONG_LIST && DEFAULT_COLLAPSED_BANDS.includes(key);
  };
  return { isFolded, flip: (key: string) => toggle(key, isFolded(key)) };
}

function ConversationList({
  conversations = [],
  total,
  view,
  onViewChange,
  isFiltered,
  onClearFilters,
  currentConversationId,
  isLoading,
  onSelect,
  onDelete,
  onArchive,
  onUnarchive,
  onFavourite,
  onRename,
  onNavigate,
  onLoadMore,
  datedOrder,
}: ConversationListProps) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const [shareConversationId, setShareConversationId] = useState<string | null>(null);

  const handleSelect = (id: string) => {
    onSelect(id);
    onNavigate?.();
  };

  const isArchivedView = view === "archived";
  const bands = useBands(conversations, currentConversationId, isArchivedView, datedOrder);
  const { isFolded, flip } = useBandFolds(bands, conversations.length);
  const foldedKeys = bands
    .filter((band) => isFolded(band.key))
    .map((band) => band.key)
    .join();

  // Scrolling to the foot is what asks for the next page, and a list with folded
  // bands, or a short first page, has no foot to scroll to - Yesterday then never
  // arrived, and vanished whenever a new chat refreshed the list to its first page.
  // Asked here instead, until the column is full or the list has ended - or the
  // last page drew nothing: rows that land in folded bands add no height, and
  // asking again for every one of them downloaded the whole history.
  const scrollerRef = useRef<HTMLDivElement>(null);
  const pagedAtHeight = useRef<number | null>(null);
  useEffect(() => {
    const scroller = scrollerRef.current;
    if (scroller === null || isLoading) return;
    const height = scroller.scrollHeight;
    if (height - scroller.clientHeight >= 100 || pagedAtHeight.current === height) return;
    pagedAtHeight.current = height;
    onLoadMore?.();
  }, [conversations.length, foldedKeys, isLoading, onLoadMore]);

  // The band the open conversation lands in opens, once per conversation - a new
  // chat in a folded Today is otherwise a thread you are in that the list hides.
  // Once: folding that band again afterwards is the reader's choice and stays.
  const unfoldedFor = useRef<string | null>(null);
  useEffect(() => {
    if (currentConversationId === null || unfoldedFor.current === currentConversationId) return;
    const band = bands.find((entry) =>
      entry.rows.some((conversation) => conversation.id === currentConversationId),
    );
    if (band === undefined) return;
    unfoldedFor.current = currentConversationId;
    if (isFolded(band.key)) flip(band.key);
  }, [bands, currentConversationId, isFolded, flip]);

  return (
    <>
      {/* Where the archive is said, since the switch to it now sits behind
          the filter button: a list of old threads with nothing saying so reads
          as the active list gone strange. */}
      {isArchivedView && (
        <div className="text-muted-foreground flex items-center justify-between px-4 pb-2 text-xs">
          <span className="flex items-center gap-1.5">
            <Archive className="h-3.5 w-3.5" aria-hidden />
            {ts("archived")}
          </span>
          <button
            type="button"
            onClick={() => onViewChange("active")}
            className="hover:text-foreground underline-offset-2 hover:underline"
          >
            {ts("backToActive")}
          </button>
        </div>
      )}

      <div
        ref={scrollerRef}
        className="flex-1 scrollbar-thin overflow-y-auto px-3 pb-3"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (!isLoading && el.scrollHeight - el.scrollTop - el.clientHeight < 100) {
            onLoadMore?.();
          }
        }}
      >
        {isLoading && conversations.length === 0 ? (
          <div className="space-y-2 py-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-9 w-full rounded-md" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          /* Three sentences, not one. "You have no conversations", "you have
             none archived" and "none of them match this filter" are three
             different situations, and the last one is the only one with an
             action attached to it. */
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <span
              aria-hidden
              className="bg-muted text-muted-foreground mb-4 flex h-12 w-12 items-center justify-center rounded-full"
            >
              {isFiltered ? (
                <SearchX className="h-5 w-5" />
              ) : isArchivedView ? (
                <Archive className="h-5 w-5" />
              ) : (
                <MessageSquare className="h-5 w-5" />
              )}
            </span>
            <p className="text-foreground text-sm font-medium">
              {isFiltered
                ? ts("noMatches")
                : isArchivedView
                  ? ts("noArchived")
                  : t("noConversations")}
            </p>
            <p className="text-muted-foreground mt-1 text-xs">
              {isFiltered
                ? ts("noMatchesHint")
                : isArchivedView
                  ? ts("archivedHint")
                  : t("startNewChat")}
            </p>
            {isFiltered && (
              <Button variant="outline" size="sm" className="mt-3" onClick={onClearFilters}>
                {ts("clearFilters")}
              </Button>
            )}
          </div>
        ) : (
          <div>
            {/* The count says what a filter or the archive narrowed to; on the
                plain list the days are the structure, and a number over them
                is one more thing to read. */}
            {(isFiltered || isArchivedView) && (
              <p className="text-muted-foreground px-2 pb-1 text-xs">
                {ts("counted", { count: total })}
              </p>
            )}
            {bands.map(({ key, heading, icon, rows }) => (
              <div key={key} className="space-y-0.5">
                {heading !== null && (
                  // A heading that folds its band away and opens it again; folded,
                  // it says how many it holds, so nothing hidden goes unmentioned.
                  <button
                    type="button"
                    aria-expanded={!isFolded(key)}
                    onClick={() => flip(key)}
                    className="group/band text-muted-foreground hover:text-foreground flex w-full items-center gap-1.5 rounded-md px-2 pt-3 pb-1 text-left text-xs font-medium transition-colors"
                  >
                    {icon === "star" && <Star className="h-3.5 w-3.5" aria-hidden />}
                    {icon === "unread" && <Inbox className="h-3.5 w-3.5" aria-hidden />}
                    {icon === "project" && <ProjectTile name={heading} />}
                    <span>{heading}</span>
                    {isFolded(key) && (
                      <span className="text-muted-foreground/70 tabular-nums">{rows.length}</span>
                    )}
                    <ChevronDown
                      className={cn(
                        "ml-auto h-3.5 w-3.5 opacity-0 transition-[transform,opacity] group-hover/band:opacity-100 group-focus-visible/band:opacity-100",
                        isFolded(key) && "-rotate-90 opacity-100",
                      )}
                      aria-hidden
                    />
                  </button>
                )}
                {!(heading !== null && isFolded(key)) &&
                  rows.map((conversation) => (
                    <ConversationItem
                      key={conversation.id}
                      conversation={conversation}
                      isActive={conversation.id === currentConversationId}
                      onSelect={() => handleSelect(conversation.id)}
                      onDelete={() => onDelete(conversation.id)}
                      onArchive={() => onArchive(conversation.id)}
                      onUnarchive={() => onUnarchive(conversation.id)}
                      onFavourite={(favourite) => onFavourite(conversation.id, favourite)}
                      onRename={(title) => onRename(conversation.id, title)}
                      onShare={() => setShareConversationId(conversation.id)}
                    />
                  ))}
              </div>
            ))}
          </div>
        )}
      </div>
      {shareConversationId && (
        <ShareDialog
          conversationId={shareConversationId}
          open={!!shareConversationId}
          onOpenChange={(open) => {
            if (!open) setShareConversationId(null);
          }}
        />
      )}
    </>
  );
}

interface ConversationSidebarProps {
  className?: string;
}

export function ConversationSidebar({ className }: ConversationSidebarProps) {
  const ts = useTranslations("chat.sidebar");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const collapse = () => setIsCollapsed(true);
  const { isOpen, close } = useChatSidebarStore();
  // Seeded from the URL and written back to it, so a reload lands on the list
  // somebody was reading rather than on the default one. Written with
  // `setUrlParam` - a `replaceState`, like `?id=` beside it - because a router
  // navigation per keystroke would re-render the whole chat.
  const searchParams = useSearchParams();
  const [view, setView] = useState<ConversationView>(
    searchParams.get("view") === "archived" ? "archived" : "active",
  );
  const [agentId, setAgentId] = useState<string | null>(searchParams.get("agent"));
  // Hidden unless asked for: an organization key's runs open a conversation
  // each, and a script calling the API every minute buried the chats a person
  // came here for. `?api=show` brings them back.
  const [hideApi, setHideApi] = useState(searchParams.get("api") !== "show");
  const [sort, setSort] = useState<ConversationSort>(() => {
    const fromUrl = searchParams.get("sort");
    return isConversationSort(fromUrl) ? fromUrl : DEFAULT_SORT;
  });

  const {
    conversations,
    total,
    currentConversationId,
    isLoading,
    fetchConversations,
    fetchMoreConversations,
    selectConversation,
    deleteConversation,
    archiveConversation,
    unarchiveConversation,
    setFavourite,
    renameConversation,
    startNewChat,
  } = useConversations({
    view,
    agentId,
    hideApi,
    ...splitSort(sort),
  });

  useEffect(() => {
    const controller = new AbortController();
    void fetchConversations(controller.signal);
    return () => controller.abort();
  }, [fetchConversations]);

  // A link to another thread followed from this page - the inbox's "answered
  // while you were away" - is a same-page navigation: nothing remounts, so the
  // effect above never sees the new `?id=`, and the address said one thread while
  // the chat showed another. Acted on only when the address moves, and only when
  // it disagrees: a thread picked here writes `?id=` after it is already open.
  const linkedId = searchParams.get("id");
  const lastLinked = useRef(linkedId);
  useEffect(() => {
    if (lastLinked.current === linkedId) return;
    lastLinked.current = linkedId;
    if (linkedId !== null && linkedId !== currentConversationId) void selectConversation(linkedId);
  }, [linkedId, currentConversationId, selectConversation]);

  const changeView = (next: ConversationView) => {
    setView(next);
    setUrlParam("view", next === "active" ? null : next);
  };
  const changeAgent = (next: string | null) => {
    setAgentId(next);
    setUrlParam("agent", next);
  };
  const changeSort = (next: ConversationSort) => {
    setSort(next);
    setUrlParam("sort", next === DEFAULT_SORT ? null : next);
  };
  const changeHideApi = (next: boolean) => {
    setHideApi(next);
    setUrlParam("api", next ? null : "show");
  };
  const clearFilters = () => {
    changeAgent(null);
    // Back to the default, which hides them - not to "everything".
    changeHideApi(true);
  };

  const listProps = {
    conversations,
    total,
    view,
    onViewChange: changeView,
    // The sort is not a filter: it reorders the same threads, so an empty list
    // under it is empty for some other reason and "clear the filters" would do
    // nothing a reader could see.
    isFiltered: agentId !== null,
    onClearFilters: clearFilters,
    currentConversationId,
    isLoading,
    onSelect: selectConversation,
    onDelete: deleteConversation,
    onArchive: archiveConversation,
    onUnarchive: unarchiveConversation,
    onFavourite: setFavourite,
    onRename: renameConversation,
    onLoadMore: fetchMoreConversations,
    datedOrder: sort === DEFAULT_SORT,
  };

  // The list's own controls, in its header beside the title the way a chat
  // app heads its list: search in a window of its own, the filters, and a new
  // chat. A row of them under the header, and a search box and a New chat
  // button before that, sat between the title and the first conversation.
  // The rail stands the same three in a column, in the same order, so collapsing
  // the list changes its width and nothing a hand has learned.
  const toolbar = (afterNewChat?: () => void, column = false) => (
    <div className={cn("flex items-center gap-0.5", column && "flex-col")}>
      <IconButton
        size="icon"
        aria-label={ts("searchLabel")}
        title={ts("searchLabel")}
        onClick={() => setSearchOpen(true)}
        className={HEADER_ICON}
      >
        <Search />
      </IconButton>
      <ConversationFilters
        agentId={agentId}
        onAgentChange={changeAgent}
        sort={sort}
        onSortChange={changeSort}
        hideApi={hideApi}
        onHideApiChange={changeHideApi}
        view={view}
        onViewChange={changeView}
        beside={column}
      />
      <IconButton
        size="icon"
        data-tour="chat-start"
        aria-label={ts("newChat")}
        title={ts("newChat")}
        onClick={() => {
          startNewChat();
          afterNewChat?.();
        }}
        className={HEADER_ICON}
      >
        <SquarePen />
      </IconButton>
    </div>
  );
  const searchDialog = (
    <ConversationSearchDialog
      open={searchOpen}
      onOpenChange={setSearchOpen}
      onSelect={(id) => {
        selectConversation(id);
        close();
      }}
    />
  );

  if (isCollapsed) {
    return (
      <>
        {searchDialog}
        <CollapsedSidebar
          {...listProps}
          toolbar={toolbar(undefined, true)}
          onExpand={() => setIsCollapsed(false)}
          className={className}
        />
      </>
    );
  }

  return (
    <>
      <aside className={cn("bg-sidebar hidden w-64 shrink-0 flex-col border-r md:flex", className)}>
        <div className="flex h-12 items-center gap-1 border-b pr-2 pl-4">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{ts("title")}</h2>
          {toolbar()}
          <IconButton
            size="icon"
            onClick={collapse}
            aria-label={ts("collapse")}
            title={ts("collapse")}
            className={HEADER_ICON}
          >
            <ChevronLeft />
          </IconButton>
        </div>
        <ConversationList {...listProps} />
      </aside>

      {searchDialog}

      <Sheet open={isOpen} onOpenChange={close}>
        <SheetContent side="left" className="w-80 p-0">
          <SheetHeader className="h-12 px-4">
            <SheetTitle className="min-w-0 flex-1 truncate">{ts("title")}</SheetTitle>
            {toolbar(close)}
            <SheetClose onClick={close} />
          </SheetHeader>
          <div className="flex h-[calc(100%-48px)] flex-col">
            <ConversationList {...listProps} onNavigate={close} />
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}

/**
 * The sidebar as a 48px rail: the same list, with the titles taken away.
 *
 * It used to be a different thing - expand, new chat, search and an Archive
 * button over the first eight threads in server order - so collapsing the list
 * moved its controls, dropped the unread and favourite bands, and lost the dot
 * that says an answer is waiting. Now it reads the bands the list does, heads
 * each with the same mark (a divider where the list has a date), folds a band
 * the list has folded, draws each thread's face with its unread dot, and keeps
 * the list's own three controls in the list's order. The filter's popover opens
 * beside the rail rather than under a 48px column.
 */
function CollapsedSidebar({
  conversations,
  view,
  currentConversationId,
  isLoading,
  onSelect,
  onLoadMore,
  datedOrder,
  toolbar,
  onExpand,
  className,
}: Pick<
  ConversationListProps,
  | "conversations"
  | "view"
  | "currentConversationId"
  | "isLoading"
  | "onSelect"
  | "onLoadMore"
  | "datedOrder"
> & {
  toolbar: ReactNode;
  onExpand: () => void;
  className?: string;
}) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const isArchivedView = view === "archived";
  const bands = useBands(conversations, currentConversationId, isArchivedView, datedOrder);
  const { isFolded, flip } = useBandFolds(bands, conversations.length);

  return (
    <div className={cn("bg-sidebar hidden w-12 shrink-0 flex-col border-r md:flex", className)}>
      {/* The same 48px header the list has, with its chevron where the list's is. */}
      <div className="flex h-12 shrink-0 items-center justify-center border-b">
        <IconButton
          size="icon"
          onClick={onExpand}
          aria-label={ts("expand")}
          title={ts("expand")}
          className={HEADER_ICON}
        >
          <ChevronRight />
        </IconButton>
      </div>
      <div className="flex shrink-0 justify-center py-2">{toolbar}</div>
      <span aria-hidden className="bg-border mx-auto h-px w-6 shrink-0" />

      <div
        className="flex flex-1 scrollbar-none flex-col items-center overflow-y-auto py-1"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (!isLoading && el.scrollHeight - el.scrollTop - el.clientHeight < 100) {
            onLoadMore?.();
          }
        }}
      >
        {isArchivedView && (
          <span
            title={ts("archived")}
            aria-label={ts("archived")}
            role="img"
            className="text-muted-foreground flex h-8 w-10 items-center justify-center"
          >
            <Archive className="h-3.5 w-3.5" aria-hidden />
          </span>
        )}
        {bands.map(({ key, heading, icon, rows }, index) => {
          const folded = heading !== null && isFolded(key);
          return (
            <div key={key} className="flex flex-col items-center gap-0.5">
              {heading !== null && (
                // The band's heading, shrunk to its mark: the list's icon where it
                // has one, a short rule where it has a date. It folds the band in
                // both places, because it is the same setting.
                <button
                  type="button"
                  aria-expanded={!folded}
                  aria-label={heading}
                  title={heading}
                  onClick={() => flip(key)}
                  className="text-muted-foreground hover:text-foreground flex h-7 w-10 items-center justify-center rounded-md transition-colors"
                >
                  {icon === "star" ? (
                    <Star className="h-3.5 w-3.5" aria-hidden />
                  ) : icon === "unread" ? (
                    <Inbox className="h-3.5 w-3.5" aria-hidden />
                  ) : icon === "project" ? (
                    <ProjectTile name={heading} />
                  ) : (
                    <span
                      aria-hidden
                      className={cn(
                        "h-px w-4 bg-current opacity-40",
                        index === 0 && !isArchivedView && "opacity-0",
                      )}
                    />
                  )}
                </button>
              )}
              {!folded &&
                rows.map((conversation) => {
                  const title = conversation.title || t("newConversation");
                  const isActive = conversation.id === currentConversationId;
                  const unread = conversation.unread === true && !isActive;
                  return (
                    <button
                      key={conversation.id}
                      type="button"
                      onClick={() => onSelect(conversation.id)}
                      title={title}
                      aria-label={title}
                      aria-current={isActive ? "true" : undefined}
                      className={cn(
                        "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition-colors",
                        isActive ? "bg-accent" : "hover:bg-accent/60",
                      )}
                    >
                      <span className="relative">
                        {conversation.agents && conversation.agents.length > 0 ? (
                          <ConversationAgents agents={conversation.agents} showName={false} />
                        ) : (
                          <span className="flex size-6 items-center justify-center">
                            <MessageSquare className="text-muted-foreground h-4 w-4" aria-hidden />
                          </span>
                        )}
                        {unread && (
                          <span
                            role="status"
                            aria-label={ts("unread")}
                            className="unread-dot ring-sidebar absolute -top-px -right-px h-2 w-2 rounded-full ring-2"
                          />
                        )}
                      </span>
                    </button>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
