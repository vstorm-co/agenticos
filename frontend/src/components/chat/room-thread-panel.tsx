"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useRoomThread } from "@/hooks/use-room-thread";
import { useMessageJump } from "@/hooks/use-message-jump";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { useTenantId } from "@/hooks/use-organizations";
import { useAgents } from "@/hooks/use-agents";
import { conversationMessageToChatMessage } from "@/lib/conversation-to-chat";
import { dockedPlan } from "@/lib/plan-state";
import { useAuthStore, useChatStore, useConversationStore } from "@/stores";
import { MessageList, type MessagePinActions } from "./message-list";
import { PinnedMessages, type PinnedMessageTarget } from "./pinned-messages";
import { MessageJumpNotice } from "./message-jump-notice";
import { MessageItem } from "./message-item";
import { PlanStrip } from "./plan-strip";
import { RoomComposer } from "./team-room-composer";
import { RoomRoutingPanel } from "./room-routing-panel";

const OVERLAY_QUERY = "(max-width: 1023px)";

function subscribeOverlay(onChange: () => void): () => void {
  const media = window.matchMedia(OVERLAY_QUERY);
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

export function RoomThreadPanel({
  conversationId,
  projectId,
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
  projectId: string | null;
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
  const t = useTranslations("chat.roomThread");
  const { agents } = useAgents({ includeArchived: true });
  const query = useRoomThread(conversationId, rootId);
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
  const canPost = projectId !== null && !readOnly && page?.can_post === true;
  const scroll = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const close = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const returnFocus = useRef<Element | null>(null);
  const jumpingAway = useRef(false);
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
  }, [last?.id, last?.content, messages.length]);
  // The load button supplies the scroller it is mounted inside; after the read,
  // the same element must still belong to this panel before restoring its place.
  const earlier = async (target: HTMLDivElement) => {
    const height = target.scrollHeight;
    const top = target.scrollTop;
    follow.current = false;
    await query.fetchNextPage();
    requestAnimationFrame(() => {
      if (scroll.current === target) target.scrollTop = top + target.scrollHeight - height;
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
              aria-label={t("close")}
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
                  {t(projectId === null ? "historyAudience" : "audience")}
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
                }}
              >
                <section className="bg-muted/40 mb-5 rounded-xl border p-3">
                  <p className="text-muted-foreground mb-2 text-xs font-medium">{t("root")}</p>
                  {preview && (
                    <MessageItem
                      message={preview}
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
                <p className="text-muted-foreground mb-3 text-xs">
                  {t("replies", { count: page.total })}
                </p>
                {projectId !== null && (
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
                {projectId !== null && canPost ? (
                  <RoomComposer
                    conversationId={conversationId}
                    projectId={projectId}
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
