"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useConversations } from "@/hooks";
import { Button, Skeleton } from "@/components/ui";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { useDebounced } from "@/components/ui/list-controls";
import { ConversationAgents } from "@/components/agents/conversation-agents";
import { cn, setUrlParam } from "@/lib/utils";
import { useChatSidebarStore } from "@/stores";
import {
  Archive,
  ArchiveRestore,
  ChevronLeft,
  ChevronRight,
  MessageSquare,
  MoreVertical,
  Pencil,
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

interface ConversationItemProps {
  conversation: Conversation;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
  onArchive: () => void;
  onUnarchive: () => void;
  onRename: (title: string) => void;
  onShare: () => void;
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
}: ConversationItemProps) {
  const t = useTranslations("chat");
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

  return (
    <div
      className={cn(
        "group relative flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl px-3 py-3 text-sm transition-all",
        isActive
          ? "bg-accent text-foreground border-border border"
          : "text-muted-foreground hover:bg-secondary/50 hover:text-secondary-foreground border border-transparent",
      )}
      onClick={onSelect}
    >
      {isActive && (
        <span
          aria-hidden
          className="bg-foreground absolute top-1/2 left-0 h-5 w-0.5 -translate-y-1/2 rounded-r-full"
        />
      )}
      <MessageSquare className={cn("h-4 w-4 shrink-0", isActive && "text-foreground")} />
      {isEditing ? (
        <input
          type="text"
          value={editTitle}
          onChange={(e) => setEditTitle(e.target.value)}
          onBlur={handleRename}
          onKeyDown={(e) => {
            if (e.key === t("enter3")) handleRename();
            if (e.key === t("escape3")) setIsEditing(false);
          }}
          className="text-foreground flex-1 bg-transparent outline-none"
          autoFocus
          onClick={(e) => e.stopPropagation()}
        />
      ) : (
        <div className="min-w-0 flex-1">
          <span className="block truncate">{displayTitle}</span>
          <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 truncate text-[10px]">
            {new Date(conversation.updated_at || conversation.created_at).toLocaleDateString(
              undefined,
              { month: "short", day: "numeric" },
            )}
            {/* Which agent this was with, as a face and nothing more. The name
                was repeating what the picture already says, in a row that also
                has to fit a title and a date - and it is on the hover title for
                the times somebody cannot tell two avatars apart. A thread that
                changed agents mid-way shows every face rather than naming only
                the latest. */}
            <ConversationAgents agents={conversation.agents} showName={false} />
          </span>
        </div>
      )}

      <div className="relative">
        <Button
          variant="ghost"
          size="sm"
          className={cn(
            "touch:opacity-100 h-8 w-8 p-0 opacity-0 group-hover:opacity-100",
            showMenu && "opacity-100",
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
            <div className="bg-popover absolute top-8 right-0 z-20 w-40 rounded-md border shadow-lg">
              <button
                className="hover:bg-secondary flex min-h-[44px] w-full items-center gap-2 px-3 py-3 text-sm"
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
                className="hover:bg-secondary flex min-h-[44px] w-full items-center gap-2 px-3 py-3 text-sm"
                onClick={(e) => {
                  e.stopPropagation();
                  onShare();
                  setShowMenu(false);
                }}
              >
                <Share2 className="h-4 w-4" />
                {t("share")}
              </button>
              {conversation.is_archived ? (
                <button
                  className="hover:bg-secondary flex min-h-[44px] w-full items-center gap-2 px-3 py-3 text-sm"
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
                  className="hover:bg-secondary flex min-h-[44px] w-full items-center gap-2 px-3 py-3 text-sm"
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
                className="text-destructive hover:bg-destructive/10 flex min-h-[44px] w-full items-center gap-2 px-3 py-3 text-sm"
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
  filters: ReactNode;
  currentConversationId: string | null;
  isLoading: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onArchive: (id: string) => void;
  onUnarchive: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onNewChat: () => void;
  onNavigate?: () => void;
  onLoadMore?: () => void;
}

function ConversationList({
  conversations = [],
  total,
  view,
  onViewChange,
  isFiltered,
  onClearFilters,
  filters,
  currentConversationId,
  isLoading,
  onSelect,
  onDelete,
  onArchive,
  onUnarchive,
  onRename,
  onNewChat,
  onNavigate,
  onLoadMore,
}: ConversationListProps) {
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const [shareConversationId, setShareConversationId] = useState<string | null>(null);

  const handleSelect = (id: string) => {
    onSelect(id);
    onNavigate?.();
  };

  const handleNewChat = () => {
    onNewChat();
    onNavigate?.();
  };

  const isArchivedView = view === "archived";

  return (
    <>
      <div className="px-3 pt-3 pb-2">
        <button
          type="button"
          onClick={handleNewChat}
          className="text-muted-foreground hover:text-foreground hover:bg-secondary flex h-9 w-full items-center gap-2 rounded-lg px-3 text-sm font-medium transition-colors"
        >
          <SquarePen className="h-4 w-4 shrink-0" />
          {t("newChat")}
        </button>
      </div>

      {filters}

      <div className="px-3 pb-2">
        <div className="bg-secondary/50 flex rounded-lg p-0.5">
          {/* No count on the tab. The one that used to sit here counted the
              pages the sidebar had fetched, so it read "Active 8 · Archived 2"
              in a deployment holding hundreds. The honest number is the
              server's, it describes one list rather than two, and it goes
              below - where it can also say that a filter is what narrowed it. */}
          <ViewTab
            label={ts("active")}
            active={view === "active"}
            onClick={() => onViewChange("active")}
          />
          <ViewTab
            label={ts("archived")}
            active={view === "archived"}
            onClick={() => onViewChange("archived")}
          />
        </div>
      </div>

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
          <div className="space-y-1">
            <p className="text-muted-foreground px-1 pb-1 text-[10px]">
              {ts("counted", { count: total })}
            </p>
            {conversations.map((conversation) => (
              <ConversationItem
                key={conversation.id}
                conversation={conversation}
                isActive={conversation.id === currentConversationId}
                onSelect={() => handleSelect(conversation.id)}
                onDelete={() => onDelete(conversation.id)}
                onArchive={() => onArchive(conversation.id)}
                onUnarchive={() => onUnarchive(conversation.id)}
                onRename={(title) => onRename(conversation.id, title)}
                onShare={() => setShareConversationId(conversation.id)}
              />
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
  const t = useTranslations("chat");
  const ts = useTranslations("chat.sidebar");
  const [isCollapsed, setIsCollapsed] = useState(false);
  const { isOpen, close } = useChatSidebarStore();
  // Seeded from the URL and written back to it, so a reload lands on the list
  // somebody was reading rather than on the default one. Written with
  // `setUrlParam` - a `replaceState`, like `?id=` beside it - because a router
  // navigation per keystroke would re-render the whole chat.
  const searchParams = useSearchParams();
  const [view, setView] = useState<ConversationView>(
    searchParams.get("view") === "archived" ? "archived" : "active",
  );
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [agentId, setAgentId] = useState<string | null>(searchParams.get("agent"));
  const [sort, setSort] = useState<ConversationSort>(() => {
    const fromUrl = searchParams.get("sort");
    return isConversationSort(fromUrl) ? fromUrl : DEFAULT_SORT;
  });
  // The request is what the search box is *for*, so it waits until the typing
  // stops. Without this the sidebar issues a round trip per keystroke and the
  // answers can land out of order.
  const debouncedSearch = useDebounced(search);

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
    renameConversation,
    startNewChat,
  } = useConversations({
    view,
    search: debouncedSearch,
    agentId,
    ...splitSort(sort),
  });

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const changeView = (next: ConversationView) => {
    setView(next);
    setUrlParam("view", next === "active" ? null : next);
  };
  const changeSearch = (next: string) => {
    setSearch(next);
    setUrlParam("q", next.trim() || null);
  };
  const changeAgent = (next: string | null) => {
    setAgentId(next);
    setUrlParam("agent", next);
  };
  const changeSort = (next: ConversationSort) => {
    setSort(next);
    setUrlParam("sort", next === DEFAULT_SORT ? null : next);
  };
  const clearFilters = () => {
    changeSearch("");
    changeAgent(null);
  };

  const listProps = {
    conversations,
    total,
    view,
    onViewChange: changeView,
    // The sort is not a filter: it reorders the same threads, so an empty list
    // under it is empty for some other reason and "clear the filters" would do
    // nothing a reader could see.
    isFiltered: debouncedSearch.trim() !== "" || agentId !== null,
    onClearFilters: clearFilters,
    filters: (
      <ConversationFilters
        search={search}
        onSearchChange={changeSearch}
        agentId={agentId}
        onAgentChange={changeAgent}
        sort={sort}
        onSortChange={changeSort}
      />
    ),
    currentConversationId,
    isLoading,
    onSelect: selectConversation,
    onDelete: deleteConversation,
    onArchive: archiveConversation,
    onUnarchive: unarchiveConversation,
    onRename: renameConversation,
    onNewChat: startNewChat,
    onLoadMore: fetchMoreConversations,
  };

  if (isCollapsed) {
    return (
      <div
        className={cn(
          "bg-background hidden w-12 flex-col items-center border-r py-4 md:flex",
          className,
        )}
      >
        <Button
          variant="ghost"
          size="sm"
          className="mb-4 h-10 w-10 p-0"
          onClick={() => setIsCollapsed(false)}
          aria-label={ts("expand")}
        >
          <ChevronRight className="h-4 w-4" aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="h-10 w-10 p-0"
          onClick={startNewChat}
          title={ts("newChat")}
          aria-label={ts("newChatLabel")}
        >
          <SquarePen className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    );
  }

  return (
    <>
      <aside
        className={cn("bg-background hidden w-64 shrink-0 flex-col border-r md:flex", className)}
      >
        <div className="flex h-12 items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">{t("conversations")}</h2>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 w-8 p-0"
            onClick={() => setIsCollapsed(true)}
            aria-label={ts("collapse")}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        <ConversationList {...listProps} />
      </aside>

      <Sheet open={isOpen} onOpenChange={close}>
        <SheetContent side="left" className="w-80 p-0">
          <SheetHeader className="h-12 px-4">
            <SheetTitle>{t("conversations")}</SheetTitle>
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

function ViewTab({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {label}
    </button>
  );
}
