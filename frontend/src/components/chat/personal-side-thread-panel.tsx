"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui";
import { useConversations } from "@/hooks/use-conversations";
import { useTenantId } from "@/hooks/use-organizations";
import type { ConversationForkRead } from "@/lib/conversation-forks-api";
import { ChatScope } from "@/stores/chat-scope";
import { useAuthStore, useConversationStore } from "@/stores";

import { ChatContainer } from "./chat-container";
import type { PinnedMessageTarget } from "./pinned-messages";

interface ConversationParentTarget {
  conversationId: string;
  messageId: string | null;
}

/** A forked child with its own conversation stores and transcript. */
export function PersonalSideThreadPanel({
  sourceConversationId,
  fork,
  onClose,
  onOpenParent,
}: {
  sourceConversationId: string;
  fork: ConversationForkRead;
  onClose: () => void;
  onOpenParent: (target: ConversationParentTarget) => void;
}) {
  const t = useTranslations("chat.sideThreads");
  const [open, setOpen] = useState(true);
  const pendingParentTarget = useRef<ConversationParentTarget | null>(null);
  const tenantId = useTenantId();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const originMatches = fork.forked_from.conversation_id === sourceConversationId;
  const identityIsReady = Boolean(tenantId && userId);
  const scopeKey = [
    tenantId ?? "signed-out",
    userId ?? "no-user",
    sourceConversationId,
    fork.id,
  ].join(":");
  const requestParentOpen = (target: ConversationParentTarget) => {
    pendingParentTarget.current = target;
    setOpen(false);
  };

  return (
    <Sheet
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen);
        if (!nextOpen && pendingParentTarget.current === null) onClose();
      }}
    >
      <SheetContent
        side="right"
        className="bg-background w-full p-0 sm:max-w-2xl"
        onCloseAutoFocus={(event) => {
          const target = pendingParentTarget.current;
          if (target === null) return;
          pendingParentTarget.current = null;
          event.preventDefault();
          window.setTimeout(() => onOpenParent(target), 0);
        }}
      >
        <SheetHeader className="min-h-14 shrink-0 px-3 py-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() =>
                requestParentOpen({
                  conversationId: fork.forked_from.conversation_id,
                  messageId: fork.forked_from.message_id,
                })
              }
              className="shrink-0 gap-1.5 px-2"
            >
              <ArrowLeft className="h-4 w-4" aria-hidden />
              <span>{t("backToParent")}</span>
            </Button>
            <SheetTitle className="min-w-0 flex-1 truncate text-sm">
              {fork.title || t("untitledFork")}
            </SheetTitle>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("close")}
            onClick={() => {
              setOpen(false);
              onClose();
            }}
          >
            <X aria-hidden />
          </Button>
        </SheetHeader>
        {!originMatches || !identityIsReady ? (
          <p role="alert" className="text-muted-foreground m-auto px-6 py-8 text-center text-sm">
            {t("error")}
          </p>
        ) : (
          <div className="min-h-0 flex-1">
            <ChatScope key={scopeKey} agentId={null}>
              <ScopedSideThread forkId={fork.id} onOpenParent={requestParentOpen} />
            </ChatScope>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}

function ScopedSideThread({
  forkId,
  onOpenParent,
}: {
  forkId: string;
  onOpenParent: (target: ConversationParentTarget) => void;
}) {
  const { selectConversation } = useConversations();
  const currentConversationId = useConversationStore((state) => state.currentConversationId);
  const requested = useRef<string | null>(null);
  const [jumpTarget, setJumpTarget] = useState<PinnedMessageTarget | null>(null);
  const [messageJumpRevision, setMessageJumpRevision] = useState(0);

  useEffect(() => {
    if (currentConversationId === forkId || requested.current === forkId) return;
    requested.current = forkId;
    void selectConversation(forkId);
  }, [currentConversationId, forkId, selectConversation]);

  return (
    <ChatContainer
      requestedConversationId={forkId}
      requestedMessageId={jumpTarget?.messageId ?? null}
      requestedThreadRootId={jumpTarget?.threadRootMessageId ?? null}
      messageJumpRevision={messageJumpRevision}
      onOpenParent={onOpenParent}
      onOpenMessage={(target) => {
        if (target.conversationId !== forkId) return;
        setJumpTarget(target);
        setMessageJumpRevision((value) => value + 1);
      }}
      onOpenThread={(rootId) => {
        setJumpTarget({ messageId: rootId, threadRootMessageId: rootId });
        setMessageJumpRevision((value) => value + 1);
      }}
      onCloseThread={() => setJumpTarget(null)}
    />
  );
}
