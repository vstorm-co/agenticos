"use client";

import { ProjectAvatar } from "@/components/projects/project-avatar";

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useAgents, useConversations } from "@/hooks";
import { ConversationSearchDialog } from "@/components/chat/conversation-search-dialog";
import type { ConversationMessageSearchTarget } from "@/lib/conversation-message-search-api";
import { Button, Skeleton } from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { IconButton } from "@/components/ui";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useConversationAgentLabel } from "@/hooks/use-conversation-agent-label";
import { ConversationAgents } from "@/components/agents/conversation-agents";
import { cn, setUrlParam, timeAgo } from "@/lib/utils";
import {
  useAgentSelectionStore,
  useChatBandsStore,
  useChatListModeStore,
  useChatSidebarStore,
  useWorkingStore,
  type ChatListMode,
} from "@/stores";
import { DEFAULT_COLLAPSED_BANDS, LONG_LIST } from "@/stores/chat-sidebar-store";
import { useProjects } from "@/hooks/use-projects";
import {
  useLeaveSharedConversation,
  useSharedConversations,
} from "@/hooks/use-conversation-shares";
import {
  RefreshCw,
  Archive,
  ArchiveRestore,
  Star,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  LogOut,
  Users,
  Loader2,
  MoreVertical,
  Pencil,
  Search,
  SearchX,
  Share2,
  SquarePen,
  Trash2,
} from "lucide-react";
import { InboxIcon as Inbox, ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import type { Conversation, ConversationAgent } from "@/types";
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
import { ConversationProjectPicker } from "./conversation-project-picker";

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onArchive: () => void;
  onUnarchive: () => void;
  onRename: (title: string) => void;
  onShare: () => void;
  onMoveProject: () => void;
  onFavourite: (favourite: boolean) => void;
  /** Somebody else's thread shared with the reader: theirs to rename, share, archive or delete. */
  shared?: boolean;
  /** Take a shared thread out of the reader's chats. */
  onLeave?: () => void;
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
  onMoveProject,
  onFavourite,
  shared = false,
  onLeave,
}: ConversationItemProps) {
  const t = useTranslations("chat");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const rowId = useId();
  const [showMenu, setShowMenu] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(conversation.title || "");
  const selectionRef = useRef<HTMLButtonElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const renameFromMenu = useRef(false);
  const returnFocusToRow = useRef(false);

  useEffect(() => {
    if (!isEditing && returnFocusToRow.current) {
      returnFocusToRow.current = false;
      selectionRef.current?.focus();
    }
  }, [isEditing]);

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
  const waiting = useWorkingStore((state) => state.waiting[conversation.id]);
  const tTools = useTranslations("pages.runs");
  const finishedAt = useWorkingStore((state) => state.finishedAt[conversation.id]);
  const finishedRuns = useWorkingStore((state) => state.finishedRuns[conversation.id]);
  const serverSince = conversation.running_since;
  const listedSince =
    serverSince &&
    (conversation.running_run_ids !== undefined
      ? conversation.running_run_ids.some((id) => !finishedRuns?.[id])
      : !finishedAt || Date.parse(serverSince) > Date.parse(finishedAt))
      ? serverSince
      : null;
  const runningSince = workingHere ?? listedSince;
  // The server's word, the same way: a run parked on a question in another tab
  // or on another device waits here too. This tab's own mark wins while it has
  // one; a park older than a turn this tab finished is a stale word for a run
  // that has since gone on, so it reads the same guard the running one does.
  const serverWaiting =
    conversation.waiting_status != null &&
    (!finishedAt ||
      (conversation.waiting_since != null &&
        Date.parse(conversation.waiting_since) > Date.parse(finishedAt)))
      ? conversation.waiting_status
      : null;
  const waitingStatus = waiting ?? serverWaiting;
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
  const agentLabel = useConversationAgentLabel(agents, conversation.coding_agents ?? []);

  const avatar = (
    <span className="relative shrink-0">
      {agents.length > 0 || conversation.coding_agents?.length ? (
        <ConversationAgents
          agents={agents}
          codingAgents={conversation.coding_agents}
          showName={false}
          size="md"
          unframed
        />
      ) : (
        <span className="block size-9" aria-hidden />
      )}
      {unread && (
        <span
          role="status"
          aria-label={t("sidebar.unread")}
          className="unread-dot ring-background absolute -top-px -right-px h-2 w-2 rounded-full ring-2"
        />
      )}
    </span>
  );

  return (
    <div
      className={cn(
        "group relative flex min-h-14 min-w-0 items-center gap-1 rounded-lg p-1 transition-colors",
        isActive ? "bg-accent" : "hover:bg-foreground/5",
      )}
    >
      {isEditing ? (
        <div className="flex min-h-12 min-w-0 flex-1 items-center gap-3 px-2">
          {avatar}
          <input
            ref={renameInputRef}
            type="text"
            aria-label={t("rename")}
            value={editTitle}
            onChange={(e) => setEditTitle(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                returnFocusToRow.current = true;
                handleRename();
              }
              if (e.key === "Escape") {
                e.preventDefault();
                returnFocusToRow.current = true;
                setEditTitle(conversation.title || "");
                setIsEditing(false);
              }
            }}
            className="text-foreground focus-visible:ring-ring min-w-0 flex-1 rounded-sm bg-transparent px-1 py-1 text-base font-medium outline-none focus-visible:ring-2 md:text-sm"
            autoFocus
          />
        </div>
      ) : (
        <button
          ref={selectionRef}
          type="button"
          aria-label={unread ? `${displayTitle} · ${t("sidebar.unread")}` : displayTitle}
          aria-describedby={`${rowId}-metadata`}
          title={displayTitle}
          aria-current={isActive ? "true" : undefined}
          onClick={onSelect}
          className="focus-visible:ring-ring flex min-h-12 min-w-0 flex-1 items-center gap-3 rounded-md px-2 py-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset"
        >
          {avatar}
          <span className="min-w-0 flex-1">
            <span className="flex min-w-0 items-center gap-1">
              <span
                id={`${rowId}-title`}
                className={cn(
                  "truncate text-sm leading-5",
                  unread ? "text-foreground font-semibold" : "font-medium",
                  !unread && (isActive ? "text-foreground" : "text-foreground/80"),
                )}
              >
                {displayTitle}
              </span>
              {conversation.origin === "api" && (
                <span className="border-border text-muted-foreground shrink-0 rounded border px-1 font-mono text-[10px] leading-4">
                  {t("sidebar.apiBadge")}
                </span>
              )}
            </span>
            <span
              id={`${rowId}-metadata`}
              className="text-muted-foreground block truncate text-xs leading-4"
            >
              {waitingStatus ? (
                tTools("toolState", { status: waitingStatus })
              ) : runningSince ? (
                <RunningFor key={runningSince} since={runningSince} />
              ) : (
                <>
                  {agentLabel && <>{agentLabel} · </>}
                  {timeAgo(conversation.updated_at || conversation.created_at, tTime, locale)}
                </>
              )}
            </span>
          </span>
        </button>
      )}

      <DropdownMenu open={showMenu} onOpenChange={setShowMenu} modal={false}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("conversationActions")}
            aria-describedby={isEditing ? undefined : `${rowId}-title`}
            className="text-muted-foreground hover:text-foreground touch:min-h-11 touch:min-w-11 size-8 shrink-0 p-0"
          >
            <MoreVertical className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          sideOffset={4}
          collisionPadding={12}
          className="min-w-48"
          onCloseAutoFocus={(event) => {
            // Keep focus in the inline editor when selecting Rename closes the menu.
            if (renameFromMenu.current) {
              event.preventDefault();
              renameFromMenu.current = false;
              renameInputRef.current?.focus();
            }
          }}
        >
          {shared ? (
            <>
              <DropdownMenuItem onSelect={() => onFavourite(conversation.is_favourite !== true)}>
                <Star
                  className={cn(
                    "h-4 w-4",
                    conversation.is_favourite && "text-warning fill-current",
                  )}
                />
                {conversation.is_favourite ? t("unfavourite") : t("favourite")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:bg-destructive/10 focus:text-destructive data-[highlighted]:bg-destructive/10"
                onSelect={() => onLeave?.()}
              >
                <LogOut className="h-4 w-4" />
                {t("leaveShared")}
              </DropdownMenuItem>
            </>
          ) : (
            <>
              <DropdownMenuItem
                onSelect={() => {
                  renameFromMenu.current = true;
                  setEditTitle(conversation.title || "");
                  setIsEditing(true);
                }}
              >
                <Pencil className="h-4 w-4" />
                {t("rename")}
              </DropdownMenuItem>
              {!conversation.project_id && (
                <DropdownMenuItem onSelect={onShare}>
                  <Share2 className="h-4 w-4" />
                  {t("share")}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={onMoveProject}>
                <ProjectAvatar name={conversation.project_id ?? t("moveToProject")} />
                {conversation.project_id ? t("removeFromProject") : t("moveToProject")}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onFavourite(conversation.is_favourite !== true)}>
                <Star
                  className={cn(
                    "h-4 w-4",
                    conversation.is_favourite && "text-warning fill-current",
                  )}
                />
                {conversation.is_favourite ? t("unfavourite") : t("favourite")}
              </DropdownMenuItem>
              {conversation.is_archived ? (
                <DropdownMenuItem onSelect={onUnarchive}>
                  <ArchiveRestore className="h-4 w-4" />
                  {t("restore")}
                </DropdownMenuItem>
              ) : (
                <DropdownMenuItem onSelect={onArchive}>
                  <Archive className="h-4 w-4" />
                  {t("archive")}
                </DropdownMenuItem>
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:bg-destructive/10 focus:text-destructive data-[highlighted]:bg-destructive/10"
                onSelect={onDelete}
              >
                <Trash2 className="h-4 w-4" />
                {t("delete")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
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
  /** Other people's threads shared with the reader. */
  shared?: Conversation[];
  onLeaveShared?: (id: string) => void;
  /** Laid out by the chats' bands, or gathered under the agent that answered. */
  mode: ChatListMode;
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
const HEADER_ICON =
  "text-foreground/85 hover:text-foreground touch:min-h-11 touch:min-w-11 size-8 shrink-0 rounded-lg [&_svg]:size-4";

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

/** One band of the list: what heads it, and the threads under it. */
interface Band {
  key: string;
  heading: string | null;
  icon: "star" | "unread" | "shared" | "project" | "agent" | null;
  /** The agent an agent band is named for; its face heads the band. */
  agent?: ConversationAgent;
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
 * The threads gathered under the agent that answered them, one band per agent,
 * in the order the list reached them - so the agent with the newest thread
 * heads the list. A thread that names several agents sits under the first.
 *
 * A thread no agent has answered yet, a new chat before its first run, has no
 * agent to head it: it goes in a last band of its own.
 */
export function byAgent(conversations: Conversation[], unnamed: string): Band[] {
  const bands = new Map<string, Band>();
  const withoutAgent: Conversation[] = [];
  for (const conversation of conversations) {
    const agent = conversation.agents?.[0];
    if (!agent) {
      withoutAgent.push(conversation);
      continue;
    }
    const band = bands.get(agent.id) ?? {
      key: `agent:${agent.id}`,
      heading: agent.name,
      icon: "agent",
      agent,
      rows: [],
    };
    band.rows.push(conversation);
    bands.set(agent.id, band);
  }
  return [
    ...bands.values(),
    ...(withoutAgent.length > 0
      ? [{ key: "agent:none", heading: unnamed, icon: null, rows: withoutAgent }]
      : []),
  ];
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
  shared: Conversation[] = [],
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
    // Channel participation can also put a direct share in the ordinary list.
    // Use the shared row once, retaining its reader controls in every band.
    const sharedRows = isArchivedView ? [] : shared;
    const sharedIds = new Set(sharedRows.map((conversation) => conversation.id));
    const listedRows = conversations.filter((conversation) => !sharedIds.has(conversation.id));
    const unread = isArchivedView
      ? []
      : [...listedRows, ...sharedRows].filter(
          (conversation) =>
            conversation.unread === true && conversation.id !== currentConversationId,
        );
    const remaining = listedRows.filter((conversation) => !unread.includes(conversation));
    const sharedRemaining = sharedRows.filter((conversation) => !unread.includes(conversation));
    const firstOther = remaining.findIndex((conversation) => conversation.is_favourite !== true);
    const ownStarred = isArchivedView
      ? []
      : remaining.slice(0, firstOther === -1 ? remaining.length : firstOther);
    const starred = [
      ...ownStarred,
      ...sharedRemaining.filter((conversation) => conversation.is_favourite === true),
    ];
    const ordinaryShared = sharedRemaining.filter(
      (conversation) => conversation.is_favourite !== true,
    );
    const { inProjects, outside: rest } = isArchivedView
      ? { inProjects: [], outside: remaining.slice(ownStarred.length) }
      : byProject(remaining.slice(ownStarred.length), names, ts("unnamedProject"));
    return [
      ...(unread.length > 0
        ? [{ key: "unread", heading: ts("unreadHeading"), icon: "unread" as const, rows: unread }]
        : []),
      ...(starred.length > 0
        ? [{ key: "favourites", heading: t("favourites"), icon: "star" as const, rows: starred }]
        : []),
      // Remaining direct shares, after unread and favourite rows. The archive
      // remains the reader's own listing.
      ...(!isArchivedView && ordinaryShared.length > 0
        ? [
            {
              key: "shared",
              heading: ts("sharedHeading"),
              icon: "shared" as const,
              rows: ordinaryShared,
            },
          ]
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
  }, [conversations, currentConversationId, isArchivedView, datedOrder, shared, names, t, ts]);
}

/**
 * The list in agents mode: the starred run first, as in the chats list, then one
 * band per agent. Unread and direct shares have no band here - the dot on a row
 * still says an answer is waiting.
 */
function useAgentBands(
  conversations: Conversation[],
  isArchivedView: boolean,
  shared: Conversation[],
  enabled: boolean,
): Band[] {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  return useMemo((): Band[] => {
    if (!enabled) return [];
    const sharedRows = isArchivedView ? [] : shared;
    const sharedIds = new Set(sharedRows.map((conversation) => conversation.id));
    const rows = [
      ...conversations.filter((conversation) => !sharedIds.has(conversation.id)),
      ...sharedRows,
    ];
    const starred = rows.filter((conversation) => conversation.is_favourite === true);
    const others = rows.filter((conversation) => conversation.is_favourite !== true);
    return [
      ...(starred.length > 0
        ? [{ key: "favourites", heading: t("favourites"), icon: "star" as const, rows: starred }]
        : []),
      ...byAgent(others, ts("otherAgents")),
    ];
  }, [conversations, isArchivedView, shared, enabled, t, ts]);
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
  shared,
  onLeaveShared,
  mode,
}: ConversationListProps) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const [shareConversationId, setShareConversationId] = useState<string | null>(null);
  const [projectConversationId, setProjectConversationId] = useState<string | null>(null);

  const handleSelect = (id: string) => {
    onSelect(id);
    onNavigate?.();
  };

  const isArchivedView = view === "archived";
  const chatBands = useBands(
    conversations,
    currentConversationId,
    isArchivedView,
    datedOrder,
    shared,
  );
  const agentBands = useAgentBands(conversations, isArchivedView, shared ?? [], mode === "agents");
  const bands = mode === "agents" ? agentBands : chatBands;
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
        className="min-h-0 min-w-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain px-3 pb-3"
        onScroll={(e) => {
          const el = e.currentTarget;
          if (!isLoading && el.scrollHeight - el.scrollTop - el.clientHeight < 100) {
            onLoadMore?.();
          }
        }}
      >
        {isLoading && conversations.length === 0 ? (
          <div className="space-y-1 py-2">
            {[1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-14 w-full rounded-lg" />
            ))}
          </div>
        ) : conversations.length === 0 && (shared?.length ?? 0) === 0 ? (
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
            {bands.map(({ key, heading, icon, agent, rows }) => (
              <div key={key} className="space-y-0.5">
                {heading !== null && (
                  // A heading that folds its band away and opens it again; folded,
                  // it says how many it holds, so nothing hidden goes unmentioned.
                  <button
                    type="button"
                    aria-expanded={!isFolded(key)}
                    onClick={() => flip(key)}
                    className="group/band text-muted-foreground hover:text-foreground focus-visible:ring-ring mt-3 flex min-h-8 w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-xs font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-inset"
                  >
                    {icon === "star" && <Star className="h-3.5 w-3.5" aria-hidden />}
                    {icon === "unread" && <Inbox className="h-3.5 w-3.5" aria-hidden />}
                    {icon === "shared" && <Users className="h-3.5 w-3.5" aria-hidden />}
                    {icon === "project" && <ProjectAvatar name={heading} />}
                    {icon === "agent" && agent && (
                      <ConversationAgents agents={[agent]} showName={false} size="sm" unframed />
                    )}
                    <span className="min-w-0 flex-1 truncate">{heading}</span>
                    {isFolded(key) && (
                      <span className="text-muted-foreground/70 tabular-nums">{rows.length}</span>
                    )}
                    <ChevronDown
                      className={cn(
                        "ml-auto h-3.5 w-3.5 shrink-0 transition-transform motion-reduce:transition-none",
                        isFolded(key) && "-rotate-90",
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
                      onMoveProject={() => setProjectConversationId(conversation.id)}
                      shared={
                        conversation.share_permission !== undefined
                          ? conversation.share_permission !== null
                          : shared?.some((entry) => entry.id === conversation.id) === true
                      }
                      onLeave={() => onLeaveShared?.(conversation.id)}
                    />
                  ))}
              </div>
            ))}
          </div>
        )}
      </div>
      {shareConversationId && (
        <ShareDialog
          key={shareConversationId}
          conversationId={shareConversationId}
          open={!!shareConversationId}
          onOpenChange={(open) => {
            if (!open) setShareConversationId(null);
          }}
        />
      )}
      <ConversationProjectPicker
        conversationId={projectConversationId}
        projectId={
          projectConversationId === null
            ? null
            : (conversations.find((conversation) => conversation.id === projectConversationId)
                ?.project_id ?? null)
        }
        open={projectConversationId !== null}
        onOpenChange={(open) => {
          if (!open) setProjectConversationId(null);
        }}
      />
    </>
  );
}

interface ConversationSidebarProps {
  className?: string;
  /** Opens a specific search hit, paging to its message when necessary. */
  onSelectSearchResult?: (target: ConversationMessageSearchTarget) => void;
}

/** Chats | Agents: how the list is laid out. A segmented control, one of two pressed. */
function ListModeToggle({
  mode,
  onChange,
}: {
  mode: ChatListMode;
  onChange: (mode: ChatListMode) => void;
}) {
  const ts = useTranslations("chat.sidebar");
  const options: { value: ChatListMode; label: string }[] = [
    { value: "chats", label: ts("modeChats") },
    { value: "agents", label: ts("modeAgents") },
  ];
  return (
    <div
      role="group"
      aria-label={ts("modeLabel")}
      className="bg-muted grid grid-cols-2 gap-0.5 rounded-lg p-0.5"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={mode === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "focus-visible:ring-ring min-h-8 rounded-md px-2 text-xs font-medium transition-colors outline-none focus-visible:ring-2",
            mode === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ConversationSidebar({ className, onSelectSearchResult }: ConversationSidebarProps) {
  const ts = useTranslations("chat.sidebar");
  const mode = useChatListModeStore((state) => state.mode);
  const setMode = useChatListModeStore((state) => state.setMode);
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

  // Only on the plain active list: an agent filter narrows the reader's own
  // threads, and a shared band beside it would ignore that filter.
  const sharedState = useSharedConversations(view === "active" && agentId === null);
  const shared = sharedState.items;
  const leaveShared = useLeaveSharedConversation();
  const leave = async (id: string) => {
    // A thread left while it is open is one the reader can no longer read.
    if ((await leaveShared(id)) && id === currentConversationId) startNewChat();
  };

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
    shared,
    onLeaveShared: (id: string) => void leave(id),
    mode,
  };

  // The list's own controls, in its header beside the title the way a chat
  // app heads its list: search in a window of its own, the filters, and a new
  // chat. A row of them under the header, and a search box and a New chat
  // button before that, sat between the title and the first conversation.
  // The rail stands the same three in a column, in the same order, so collapsing
  // the list changes its width and nothing a hand has learned.
  const filters = (beside = false) => (
    <ConversationFilters
      agentId={agentId}
      onAgentChange={changeAgent}
      sort={sort}
      onSortChange={changeSort}
      hideApi={hideApi}
      onHideApiChange={changeHideApi}
      view={view}
      onViewChange={changeView}
      beside={beside}
    />
  );
  const sharedNotice = sharedState.failed ? (
    <div role="alert" className="text-muted-foreground space-y-1 px-4 py-2 text-xs">
      <p>{ts("sharedFailed")}</p>
      <Button variant="ghost" size="sm" onClick={sharedState.retry}>
        {ts("retryShared")}
      </Button>
    </div>
  ) : sharedState.isLoading ? (
    <p role="status" className="text-muted-foreground flex items-center gap-2 px-4 py-2 text-xs">
      <Loader2 className="size-3 animate-spin motion-reduce:animate-none" aria-hidden />
      {ts("sharedLoading")}
    </p>
  ) : null;
  const toolbar = (afterNewChat?: () => void, column = false) => (
    <div className={cn("flex shrink-0 items-center gap-0.5", column && "flex-col")}>
      <IconButton
        size="icon"
        aria-label={ts("searchLabel")}
        data-tour="chat-message-search"
        title={ts("searchLabel")}
        onClick={() => setSearchOpen(true)}
        className={HEADER_ICON}
      >
        <Search />
      </IconButton>
      {column && filters(true)}
      {column && sharedState.failed && (
        <IconButton
          size="icon"
          aria-label={ts("retryShared")}
          title={ts("sharedFailed")}
          onClick={sharedState.retry}
          className={HEADER_ICON}
        >
          <RefreshCw />
        </IconButton>
      )}
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
  const listModeToggle = <ListModeToggle mode={mode} onChange={setMode} />;
  const searchDialog = (
    <ConversationSearchDialog
      open={searchOpen}
      onOpenChange={setSearchOpen}
      onSelect={(id) => {
        selectConversation(id);
        close();
      }}
      onSelectResult={(target) => {
        if (onSelectSearchResult) onSelectSearchResult(target);
        else selectConversation(target.conversationId);
        close();
      }}
    />
  );

  return (
    <>
      {isCollapsed ? (
        <CollapsedSidebar
          {...listProps}
          toolbar={toolbar(undefined, true)}
          onExpand={() => setIsCollapsed(false)}
          className={className}
        />
      ) : (
        <aside
          className={cn(
            "bg-sidebar-secondary hidden min-h-0 w-64 min-w-0 shrink-0 flex-col lg:flex",
            className,
          )}
        >
          <div
            className="flex h-14 shrink-0 items-center gap-1 pr-2 pl-4"
            data-tauri-drag-region="deep"
          >
            <h2 data-tauri-drag-region className="min-w-0 flex-1 truncate text-sm font-semibold">
              {ts("title")}
            </h2>
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
          <div className="shrink-0 px-3 pt-2">{listModeToggle}</div>
          <div className="shrink-0 px-3 py-2">{filters()}</div>
          {sharedNotice}
          <ConversationList {...listProps} />
        </aside>
      )}

      {searchDialog}

      <Sheet open={isOpen} onOpenChange={close}>
        <SheetContent side="left" className="w-80 p-0">
          <SheetHeader className="h-14 shrink-0 px-4">
            <SheetTitle className="min-w-0 flex-1 truncate">{ts("title")}</SheetTitle>
            {toolbar(close)}
            <SheetClose onClick={close} />
          </SheetHeader>
          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="shrink-0 px-3 pt-2">{listModeToggle}</div>
            <div className="shrink-0 px-3 py-2">{filters()}</div>
            {sharedNotice}
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
  shared,
  mode,
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
  | "shared"
  | "mode"
> & {
  toolbar: ReactNode;
  onExpand: () => void;
  className?: string;
}) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const isArchivedView = view === "archived";
  const chatBands = useBands(
    conversations,
    currentConversationId,
    isArchivedView,
    datedOrder,
    shared,
  );
  const agentBands = useAgentBands(conversations, isArchivedView, shared ?? [], mode === "agents");
  const bands = mode === "agents" ? agentBands : chatBands;
  const { isFolded, flip } = useBandFolds(bands, conversations.length);

  return (
    <div
      className={cn(
        "bg-sidebar-secondary hidden min-h-0 w-12 min-w-0 shrink-0 flex-col lg:flex",
        className,
      )}
    >
      {/* Match the expanded list's header so collapsing keeps its controls aligned. */}
      <div className="flex h-14 shrink-0 items-center justify-center" data-tauri-drag-region="deep">
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
        className="flex min-h-0 min-w-0 flex-1 scrollbar-none flex-col items-center overflow-y-auto overscroll-contain py-1"
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
        {bands.map(({ key, heading, icon, agent, rows }, index) => {
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
                  ) : icon === "shared" ? (
                    <Users className="h-3.5 w-3.5" aria-hidden />
                  ) : icon === "project" ? (
                    <ProjectAvatar name={heading} />
                  ) : icon === "agent" && agent ? (
                    <ConversationAgents
                      agents={[agent]}
                      showName={false}
                      size="sm"
                      unframed
                      compact
                    />
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
                        isActive ? "bg-accent" : "hover:bg-foreground/5",
                      )}
                    >
                      <span className="relative">
                        {conversation.agents?.length || conversation.coding_agents?.length ? (
                          <ConversationAgents
                            agents={conversation.agents}
                            codingAgents={conversation.coding_agents}
                            showName={false}
                            size="md"
                            compact
                            unframed
                          />
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
