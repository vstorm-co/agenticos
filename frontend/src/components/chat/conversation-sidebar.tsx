"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useConversations } from "@/hooks";
import { ConversationSearchDialog } from "@/components/chat/conversation-search-dialog";
import { Button, Skeleton } from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { IconButton } from "@/components/ui";
import { ConversationAgents } from "@/components/agents/conversation-agents";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { cn, setUrlParam, timeAgo } from "@/lib/utils";
import { useChatSidebarStore } from "@/stores";
import {
  Archive,
  ArchiveRestore,
  Star,
  ChevronLeft,
  ChevronRight,
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
  const agents = conversation.agents ?? [];
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
          thread by - and a thread with no agent keeps the plain mark. */}
      <span className="relative shrink-0">
        {conversation.agents && conversation.agents.length > 0 ? (
          <ConversationAgents agents={conversation.agents} showName={false} />
        ) : (
          // In a box the size of an agent's face, so every title in the list
          // starts at the same x whichever kind of row it is.
          <span className="flex size-6 items-center justify-center">
            <MessageSquare className={cn("h-4 w-4", isActive && "text-foreground")} />
          </span>
        )}
        {/* An answer arrived while the reader was elsewhere: a badge on the face,
            as a count sits on an app icon - part of the row's own mark rather
            than a stray dot at its far edge. Not on the open row, which is being
            read as it arrives. */}
        {unread && (
          <span
            role="status"
            aria-label={t("sidebar.unread")}
            className="unread-dot ring-background absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full ring-2"
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
            {agentLabel && <>{agentLabel} · </>}
            {conversation.running_since ? (
              <RunningFor since={conversation.running_since} />
            ) : (
              timeAgo(conversation.updated_at || conversation.created_at, tTime, locale)
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

      {/* Only once it is starred. As a *button* it was redundant - the same
          toggle is in the menu beside it, two rows down - and the redundancy
          cost every row in the list eight characters of title, because a
          control at `opacity-0` still takes its width. What it is not
          redundant as is a *marker*: it is the only thing on a row saying
          which band that row is in, so a favourited conversation keeps it and
          everything else gets the width back. */}
      {conversation.is_favourite ? (
        <Button
          variant="ghost"
          size="sm"
          aria-label={t("unfavourite")}
          aria-pressed
          // Neutral, like the rest of the list: the band it sits in already says
          // it is a favourite, and a brown-gold star was the one tint on the page.
          className="text-muted-foreground/70 hover:text-foreground h-6 w-6 shrink-0 p-0"
          onClick={(e) => {
            e.stopPropagation();
            onFavourite(false);
          }}
        >
          <Star className="h-3.5 w-3.5 fill-current" />
        </Button>
      ) : null}

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
function RunningFor({ since }: { since: string }) {
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
  const bands = useMemo(() => {
    const firstOther = conversations.findIndex(
      (conversation) => conversation.is_favourite !== true,
    );
    const starred = isArchivedView
      ? []
      : conversations.slice(0, firstOther === -1 ? conversations.length : firstOther);
    const rest = conversations.slice(starred.length);
    return [
      ...(starred.length > 0
        ? [{ key: "favourites", heading: t("favourites"), starred: true, rows: starred }]
        : []),
      // Under the date they were last active, the way a chat product's history
      // reads, when the list is in that order; any other order has no dates to
      // fall into, so it stays one run.
      ...(datedOrder
        ? byAge(rest).map(({ age, rows }) => ({
            key: age,
            heading: ts(`age.${age}`),
            starred: false,
            rows,
          }))
        : rest.length > 0
          ? [{ key: "rest", heading: null, starred: false, rows: rest }]
          : []),
    ];
  }, [conversations, isArchivedView, datedOrder, t, ts]);

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
            {bands.map(({ key, heading, starred, rows }) => (
              <div key={key} className="space-y-0.5">
                {heading !== null && (
                  <p className="text-muted-foreground flex items-center gap-1 px-2 pt-3 pb-1 text-xs font-medium">
                    {starred && <Star className="h-3 w-3 fill-current" aria-hidden />}
                    {heading}
                  </p>
                )}
                {rows.map((conversation) => (
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
    fetchConversations();
  }, [fetchConversations]);

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
  const toolbar = (afterNewChat?: () => void) => (
    <div className="flex items-center gap-0.5">
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
          conversations={conversations}
          currentConversationId={currentConversationId}
          view={view}
          onExpand={() => setIsCollapsed(false)}
          onSearch={() => setSearchOpen(true)}
          onViewChange={(next) => {
            changeView(next);
            setIsCollapsed(false);
          }}
          onSelect={selectConversation}
          onNewChat={startNewChat}
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

/** How many threads the rail offers. Enough to reach yesterday's work, few enough
 *  to leave the rail a rail rather than a second list. */
const RAIL_CONVERSATIONS = 8;

/**
 * The sidebar as a 48px rail.
 *
 * It used to hold two buttons - expand, and new chat - which meant collapsing the
 * sidebar gave up everything except the width. Switching to yesterday's thread cost
 * expanding, clicking and collapsing again, so nobody collapsed it.
 *
 * What it holds now is what a rail can hold honestly: the recent threads, as the
 * face of whichever agent answered in each, and the two controls that are more than
 * "expand" - search opens the sidebar with the cursor already in the box, and
 * Archived opens it on that tab. Sort and the agent filter are deliberately absent:
 * both are a menu, and a menu hanging off a 48px rail is the expanded sidebar with
 * extra steps.
 */
function CollapsedSidebar({
  conversations,
  currentConversationId,
  view,
  onExpand,
  onSearch,
  onViewChange,
  onSelect,
  onNewChat,
  className,
}: {
  conversations: Conversation[];
  currentConversationId: string | null;
  view: ConversationView;
  onExpand: () => void;
  onSearch: () => void;
  onViewChange: (view: ConversationView) => void;
  onSelect: (id: string) => void;
  onNewChat: () => void;
  className?: string;
}) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const recent = conversations.slice(0, RAIL_CONVERSATIONS);

  return (
    <div
      className={cn(
        "bg-sidebar hidden w-12 shrink-0 flex-col items-center border-r py-4 md:flex",
        className,
      )}
    >
      <Button
        variant="ghost"
        size="sm"
        className="h-10 w-10 p-0"
        onClick={onExpand}
        aria-label={ts("expand")}
      >
        <ChevronRight className="h-4 w-4" aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-10 w-10 p-0"
        onClick={onNewChat}
        title={ts("newChat")}
        aria-label={ts("newChatLabel")}
      >
        <SquarePen className="h-4 w-4" aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="h-10 w-10 p-0"
        onClick={onSearch}
        title={ts("searchLabel")}
        aria-label={ts("searchLabel")}
      >
        <Search className="h-4 w-4" aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className={cn("h-10 w-10 p-0", view === "archived" && "text-foreground bg-secondary")}
        onClick={() => onViewChange(view === "archived" ? "active" : "archived")}
        title={ts("archived")}
        aria-label={ts("archived")}
      >
        <Archive className="h-4 w-4" aria-hidden />
      </Button>

      {recent.length > 0 && (
        <>
          <span aria-hidden className="bg-border my-2 h-px w-6" />
          {/* A list, so a screen reader is told these are threads rather than four
              more toolbar buttons. The rail does not scroll: past eight, the
              sidebar is the place to look. */}
          <ul className="flex flex-col items-center gap-1">
            {recent.map((conversation) => {
              const agent = conversation.agents?.[0];
              const title = conversation.title || t("newConversation");
              const isActive = conversation.id === currentConversationId;
              return (
                <li key={conversation.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(conversation.id)}
                    title={title}
                    aria-label={title}
                    aria-current={isActive ? "true" : undefined}
                    className={cn(
                      "relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors",
                      isActive
                        ? "bg-accent text-foreground"
                        : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground",
                    )}
                  >
                    {isActive && (
                      <span
                        aria-hidden
                        className="bg-foreground absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-r-full"
                      />
                    )}
                    {agent ? (
                      <AgentAvatar
                        agentId={agent.id}
                        slug={agent.slug}
                        hasAvatar={agent.has_avatar}
                        size="sm"
                      />
                    ) : (
                      <MessageSquare className="h-4 w-4" aria-hidden />
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
