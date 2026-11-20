"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useRoomThread } from "@/hooks/use-room-thread";
import { useRoomThreadActions } from "@/hooks/use-room-thread-actions";
import { useMessageJump } from "@/hooks/use-message-jump";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { useTenantId } from "@/hooks/use-organizations";
import { useAgents } from "@/hooks/use-agents";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { dockedPlan } from "@/lib/plan-state";
import { getErrorMessage } from "@/lib/api-error";
import { useAuthStore, useChatStore, useConversationStore } from "@/stores";
import { MessageList, type MessagePinActions } from "./message-list";
import { PinnedMessages, type PinnedMessageTarget } from "./pinned-messages";
import { MessageJumpNotice } from "./message-jump-notice";
import { MessageItem } from "./message-item";
import { PlanStrip } from "./plan-strip";
import { RoomComposer } from "./team-room-composer";
import { RoomRoutingPanel } from "./room-routing-panel";
import { RoomThreadContextPanel } from "./room-thread-context-panel";

const OVERLAY_QUERY = "(max-width: 1023px)";

function subscribeOverlay(onChange: () => void): () => void {
  const media = window.matchMedia(OVERLAY_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function RoomThreadPanel({
  conversationId,
  conversationTitle = "",
  isRoom: roomMode,
  roomReactionsEnabled,
  projectId = null,
  rootId,
  requestedMessageId = null,
  messageJumpRevision = 0,
  readOnly,
  onClose,
  onTyping,
  actions,
  isProcessing,
  messagePinActions,
  onOpenPinnedMessage,
}: {
  conversationId: string;
  conversationTitle?: string;
  /** Explicit room mode also covers standalone rooms without a project id. */
  isRoom?: boolean;
  /** Whether room reaction controls belong on this transcript. */
  roomReactionsEnabled?: boolean;
  /** Kept for existing project-room callsites and test fixtures. */
  projectId?: string | null;
  rootId: string;
  requestedMessageId?: string | null;
  messageJumpRevision?: number;
  readOnly: boolean;
  onClose: () => void;
  onTyping: () => void;
  actions?: (readOnly: boolean) => ReactNode;
  isProcessing: boolean;
  messagePinActions?: MessagePinActions;
  onOpenPinnedMessage?: (target: PinnedMessageTarget) => void;
}) {
  const isRoom = roomMode ?? projectId !== null;
  const reactionsEnabled = roomReactionsEnabled ?? isRoom;
  const t = useTranslations("chat.roomThread");
  const tErrors = useTranslations("errors");
  const { agents } = useAgents({ includeArchived: true });
  const query = useRoomThread(conversationId, rootId);
  const threadActions = useRoomThreadActions(conversationId, rootId);
  const draft = useRoomDraft(conversationId, rootId);
  const accountId = useAuthStore((state) => state.user?.id ?? null);
  const tenantId = useTenantId();
  const selectionVersion = useConversationStore((state) => state.selectionVersion);
  const selectedConversation = useConversationStore((state) => state.currentConversationId);
  const loaded = useChatStore((state) => state.loadedTranscript);
  const raw = useChatStore((state) => state.messages);
  const merge = useChatStore((state) => state.rereadRoomThread);
  const selected =
    selectedConversation === conversationId &&
    loaded?.conversationId === conversationId &&
    loaded.selectionVersion === selectionVersion &&
    loaded.accountId === accountId &&
    loaded.tenantId === tenantId;
  // Cached rows never grant access: opening or changing a root requires a fresh read.
  const authorized = query.isFetchedAfterMount && query.isSuccess && !query.isError;
  const page = authorized ? query.data.pages[0] : undefined;
  const history = useMemo(() => {
    if (!authorized) return [];
    const rows = new Map(
      query.data.pages
        .toReversed()
        .flatMap((part) => part.items)
        .map((item) => [item.id, item]),
    );
    return [...rows.values()].map(conversationMessageToChatMessage);
  }, [authorized, query.data]);
  const persistedMessageIds = useMemo(
    () =>
      new Set(
        [page?.root.id, ...history.map((message) => message.id)].filter(
          (id): id is string => id !== undefined,
        ),
      ),
    [history, page?.root.id],
  );
  useEffect(() => {
    if (authorized && selected && loaded !== null) merge(history, rootId, loaded);
  }, [authorized, selected, loaded, history, rootId, merge]);
  const messages = useMemo(
    () =>
      authorized && selected
        ? raw.filter(
            (message) =>
              message.conversationId === conversationId && message.threadRootMessageId === rootId,
          )
        : [],
    [authorized, selected, raw, conversationId, rootId],
  );
  const plan = useMemo(() => dockedPlan(messages), [messages]);
  const threadState = page?.state ?? page?.root.thread_summary?.state ?? "open";
  const threadFollowing = page?.following ?? page?.root.thread_summary?.following ?? false;
  const threadUnread = page?.unread ?? page?.root.thread_summary?.unread ?? 0;
  const canManageThread = page?.can_manage ?? page?.root.thread_summary?.can_manage ?? false;
  const threadIsArchived = threadState === "archived";
  const canPost = isRoom && !readOnly && !threadIsArchived && page?.can_post === true;
  const [threadActionError, setThreadActionError] = useState<string | null>(null);
  const [visibleThroughId, setVisibleThroughId] = useState<string | null>(null);
  const [visibilityVersion, setVisibilityVersion] = useState(0);
  const lastReadMessageId = useRef<string | null>(null);
  const pendingReadMessageId = useRef<string | null>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const close = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const returnFocus = useRef<Element | null>(null);
  const jumpingAway = useRef(false);
  const updateVisibleCursor = useCallback(() => {
    if (typeof document === "undefined" || document.visibilityState !== "visible") return;
    const container = scroll.current;
    if (!container) return;
    const bounds = container.getBoundingClientRect();
    const nodes = Array.from(
      container.querySelectorAll<HTMLElement>("[data-message-id], [data-thread-root]"),
    );
    let through: string | null = null;
    for (const node of nodes) {
      const rect = node.getBoundingClientRect();
      if (rect.bottom <= bounds.top || rect.top >= bounds.bottom) continue;
      const id = node.dataset.messageId ?? node.dataset.threadRoot;
      if (id && persistedMessageIds.has(id)) through = id;
    }
    setVisibleThroughId(through);
  }, [persistedMessageIds]);

  const runThreadAction = async (operation: () => Promise<boolean>) => {
    setThreadActionError(null);
    try {
      await operation();
    } catch (error) {
      setThreadActionError(getErrorMessage(error, tErrors, t("actionFailed")));
    }
  };

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState !== "visible") return;
      setVisibilityVersion((version) => version + 1);
      updateVisibleCursor();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => document.removeEventListener("visibilitychange", onVisibilityChange);
  }, [updateVisibleCursor]);
  const overlay = useSyncExternalStore(
    subscribeOverlay,
    () => window.matchMedia(OVERLAY_QUERY).matches,
    () => false,
  );
  const last = messages.at(-1);
  const holdMessageJump = useCallback(() => {
    follow.current = false;
  }, []);
  const messageJump = useMessageJump({
    messageId: requestedMessageId,
    scope: JSON.stringify([accountId, tenantId, conversationId, selectionVersion, rootId]),
    revision: messageJumpRevision,
    ready: authorized && selected,
    messageIds: [...messages.map((message) => message.id), ...(page?.root ? [page.root.id] : [])],
    firstMessageId: history[0]?.id ?? null,
    hasEarlier: query.hasNextPage,
    loadingEarlier: query.isFetchingNextPage,
    loadEarlier: query.fetchNextPage,
    container: scroll,
    beforeJump: holdMessageJump,
  });
  useLayoutEffect(() => {
    if (follow.current && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
    updateVisibleCursor();
  }, [last?.id, last?.content, messages.length, updateVisibleCursor]);
  useEffect(() => {
    if (
      !isRoom ||
      !authorized ||
      !selected ||
      visibleThroughId === null ||
      document.visibilityState !== "visible" ||
      threadActions.isMarkingRead ||
      pendingReadMessageId.current !== null
    )
      return;
    const cursorIndex =
      visibleThroughId === page?.root.id
        ? -1
        : messages.findIndex((message) => message.id === visibleThroughId);
    if (visibleThroughId !== page?.root.id && cursorIndex < 0) return;
    const lastId = lastReadMessageId.current;
    if (lastId === visibleThroughId) return;
    const lastIndex =
      lastId === null
        ? -2
        : lastId === page?.root.id
          ? -1
          : messages.findIndex((message) => message.id === lastId);
    if (lastIndex >= -1 && cursorIndex <= lastIndex) return;

    pendingReadMessageId.current = visibleThroughId;
    void threadActions
      .markRead(visibleThroughId)
      .then((marked) => {
        if (marked) lastReadMessageId.current = visibleThroughId;
      })
      .catch((error) => {
        setThreadActionError(getErrorMessage(error, tErrors, t("actionFailed")));
      })
      .finally(() => {
        if (pendingReadMessageId.current === visibleThroughId) pendingReadMessageId.current = null;
      });
  }, [
    isRoom,
    authorized,
    selected,
    visibleThroughId,
    messages,
    page?.root.id,
    threadActions.isMarkingRead,
    threadActions.markRead,
    t,
    tErrors,
    visibilityVersion,
  ]);
  // The load button supplies the scroller it is mounted inside; after the read,
  // the same element must still belong to this panel before restoring its place.
  const earlier = async (target: HTMLDivElement) => {
    const height = target.scrollHeight;
    const top = target.scrollTop;
    follow.current = false;
    await query.fetchNextPage();
    requestAnimationFrame(() => {
      if (scroll.current === target) {
        target.scrollTop = top + target.scrollHeight - height;
        updateVisibleCursor();
      }
    });
  };
  const root = page?.root;
  const preview = useMemo(() => (root ? conversationMessageToChatMessage(root) : null), [root]);
  return (
    <DialogPrimitive.Root open modal={overlay} onOpenChange={onClose}>
      <DialogPrimitive.Content
        asChild
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          returnFocus.current = document.activeElement;
          close.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (jumpingAway.current) return;
          if (returnFocus.current instanceof HTMLElement && returnFocus.current.isConnected)
            returnFocus.current.focus();
        }}
        onInteractOutside={(event) => {
          event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          if (!overlay && !panel.current?.contains(document.activeElement)) event.preventDefault();
        }}
      >
        <aside
          ref={panel}
          role={overlay ? "dialog" : "complementary"}
          aria-modal={overlay ? true : undefined}
          aria-label={t("title")}
          data-tour="chat-room-thread-panel"
          className="bg-background absolute inset-0 z-30 flex min-h-0 min-w-0 flex-col border-l lg:relative lg:inset-auto lg:z-auto lg:w-[min(44%,34rem)] lg:min-w-80 lg:shrink-0"
        >
          <header className="flex shrink-0 items-center gap-2 border-b px-3 py-3">
            <Button
              ref={close}
              size="icon"
              variant="ghost"
              aria-label={t("closePanel")}
              onClick={onClose}
            >
              <ArrowLeft className="size-4" aria-hidden />
            </Button>
            <div className="min-w-0 flex-1">
              <DialogPrimitive.Title asChild>
                <h2 className="text-sm font-semibold">{t("title")}</h2>
              </DialogPrimitive.Title>
              <DialogPrimitive.Description asChild>
                <p className="text-muted-foreground text-xs">
                  {t(isRoom ? "audience" : "historyAudience")}
                </p>
              </DialogPrimitive.Description>
            </div>
            {authorized && selected && messagePinActions && onOpenPinnedMessage && (
              <PinnedMessages
                conversationId={conversationId}
                onJumpToMessage={(target) => {
                  jumpingAway.current = target.threadRootMessageId !== rootId;
                  onOpenPinnedMessage(target);
                }}
              />
            )}
          </header>
          {isRoom && authorized && page && (
            <div className="border-b px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="border-border text-muted-foreground rounded-full border px-2 py-1 text-[11px]">
                  {threadState === "open"
                    ? t("state.open")
                    : threadState === "closed"
                      ? t("state.closed")
                      : t("state.archived")}
                </span>
                {threadUnread > 0 && (
                  <span className="bg-primary/10 text-primary rounded-full px-2 py-1 text-[11px]">
                    {t("unreadCount", { count: threadUnread })}
                  </span>
                )}
                {threadState !== "archived" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    aria-pressed={threadFollowing}
                    disabled={threadActions.isPending}
                    onClick={() =>
                      void runThreadAction(
                        threadFollowing ? threadActions.unfollow : threadActions.follow,
                      )
                    }
                  >
                    {threadFollowing ? t("unfollow") : t("follow")}
                  </Button>
                )}
                {canManageThread && threadState === "open" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={threadActions.isPending}
                    onClick={() => void runThreadAction(() => threadActions.updateState("close"))}
                  >
                    {t("closeThread")}
                  </Button>
                )}
                {canManageThread && threadState === "closed" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={threadActions.isPending}
                    onClick={() => void runThreadAction(() => threadActions.updateState("reopen"))}
                  >
                    {t("reopenThread")}
                  </Button>
                )}
                {canManageThread && threadState !== "archived" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={threadActions.isPending}
                    onClick={() => void runThreadAction(() => threadActions.updateState("archive"))}
                  >
                    {t("archiveThread")}
                  </Button>
                )}
                {canManageThread && threadState === "archived" && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={threadActions.isPending}
                    onClick={() =>
                      void runThreadAction(() => threadActions.updateState("unarchive"))
                    }
                  >
                    {t("unarchiveThread")}
                  </Button>
                )}
              </div>
              {threadActionError && (
                <p className="text-destructive mt-2 text-xs" role="alert">
                  {threadActionError}
                </p>
              )}
            </div>
          )}
          {query.isError ? (
            <div role="alert" className="space-y-3 p-4 text-sm">
              <p>{t("unavailable")}</p>
              <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
                {t("retry")}
              </Button>
            </div>
          ) : !root ? (
            <p role="status" className="text-muted-foreground p-4 text-sm">
              {t("loading")}
            </p>
          ) : (
            <>
              <MessageJumpNotice jump={messageJump} />
              <div
                ref={scroll}
                className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4"
                onScroll={(event) => {
                  const node = event.currentTarget;
                  follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
                  updateVisibleCursor();
                }}
              >
                <section className="bg-muted/40 mb-5 rounded-xl border p-3">
                  <p className="text-muted-foreground mb-2 text-xs font-medium">{t("root")}</p>
                  {preview && (
                    <MessageItem
                      message={preview}
                      roomReactionsEnabled={reactionsEnabled}
                      canReactToRoomMessages={canPost}
                      threadRootPreview
                      allowReply={canPost}
                      onReply={draft.setReply}
                      onTogglePin={messagePinActions?.togglePin}
                      pinPending={messagePinActions?.pendingMessageId === preview.id}
                      agent={agents.find((agent) => agent.id === preview.agentId)}
                      agents={agents}
                    />
                  )}
                </section>
                {isRoom && page.context && (
                  <RoomThreadContextPanel
                    mode="thread"
                    destinationConversationId={conversationId}
                    destinationTitle={conversationTitle}
                    rootMessageId={rootId}
                    threadTitle={root.content}
                    context={page.context}
                    contextMessages={page.context_messages ?? []}
                    canManage={canManageThread}
                    threadState={threadState}
                  />
                )}
                <p className="text-muted-foreground mb-3 text-xs">
                  {t("replies", { count: page.total })}
                </p>
                {isRoom && projectId !== null && (
                  <RoomRoutingPanel
                    conversationId={conversationId}
                    threadRootMessageId={rootId}
                    readOnly={!canPost}
                  />
                )}
                {query.hasNextPage && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mb-3 w-full"
                    disabled={query.isFetchingNextPage}
                    onClick={() => void earlier(scroll.current!)}
                  >
                    {t("earlier")}
                  </Button>
                )}
                <MessageList
                  messages={messages}
                  roomReactionsEnabled={reactionsEnabled}
                  canReactToRoomMessages={canPost}
                  onReply={draft.setReply}
                  allowReply={canPost}
                  messagePinActions={messagePinActions}
                />
                {messages.length === 0 && (
                  <p className="text-muted-foreground py-6 text-center text-sm">{t("empty")}</p>
                )}
              </div>
              <div className="max-h-[60%] shrink-0 overflow-y-auto border-t px-3 pt-3 pb-4">
                {actions?.(!canPost)}
                <PlanStrip plan={plan} live={isProcessing} />
                {isRoom && canPost ? (
                  <RoomComposer
                    conversationId={conversationId}
                    allowLead={projectId !== null}
                    readOnly={false}
                    onTyping={onTyping}
                    draft={draft}
                    threadRootMessageId={rootId}
                  />
                ) : (
                  <p className="text-muted-foreground p-3 text-center text-xs">{t("readOnly")}</p>
                )}
              </div>
            </>
          )}
        </aside>
      </DialogPrimitive.Content>
    </DialogPrimitive.Root>
  );
}
