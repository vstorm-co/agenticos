"use client";

import { useState } from "react";
import { GitBranch } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button, Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { useConversationForks } from "@/hooks/use-conversation-forks";
import type { ConversationForkRead } from "@/lib/conversation-forks-api";
import { timeAgo } from "@/lib/utils";

export interface ConversationSideThreadActions {
  sourceConversationId: string;
  creatingMessageId: string | null;
  onCreate: (messageId: string) => Promise<void>;
  onOpen: (messageId: string, fork: ConversationForkRead) => void;
}

/** Forks created from one answer, with writes and opening delegated to the owning chat. */
export function ConversationSideThreads({
  sourceConversationId,
  messageId,
  creatingMessageId = null,
  onCreate,
  onOpen,
}: {
  sourceConversationId: string;
  messageId: string;
  creatingMessageId?: string | null;
  onCreate: (messageId: string) => Promise<void>;
  onOpen: (fork: ConversationForkRead) => void;
}) {
  const t = useTranslations("chat.sideThreads");
  const tChat = useTranslations("chat");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createFailed, setCreateFailed] = useState(false);
  const query = useConversationForks(sourceConversationId, messageId, open);
  const forks = (query.data?.pages.flatMap((page) => page.items) ?? []).filter(
    (fork) =>
      fork.forked_from.conversation_id === sourceConversationId &&
      fork.forked_from.message_id === messageId,
  );
  const create = async () => {
    setCreating(true);
    setCreateFailed(false);
    try {
      await onCreate(messageId);
      setOpen(false);
    } catch {
      setCreateFailed(true);
    } finally {
      setCreating(false);
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        data-tour="chat-side-threads"
        aria-expanded={open}
        onClick={() => setOpen(true)}
        className="text-muted-foreground h-8 gap-1.5 px-2"
      >
        <GitBranch className="h-3.5 w-3.5" aria-hidden />
        <span>{t("title")}</span>
        {forks.length > 0 && <span className="text-xs tabular-nums">{forks.length}</span>}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[min(36rem,80dvh)] gap-0 overflow-hidden p-0">
          <div className="border-b px-5 py-4 pr-12">
            <DialogTitle className="text-base">{t("title")}</DialogTitle>
          </div>
          <div className="min-h-24 overflow-y-auto p-2">
            {query.isError && (
              <div role="alert" className="flex items-center justify-center gap-3 px-3 py-4">
                <span className="text-muted-foreground text-sm">{t("error")}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => void query.refetch()}
                >
                  {t("retry")}
                </Button>
              </div>
            )}
            {query.isPending && (
              <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("loading")}</p>
            )}
            {query.isSuccess && forks.length === 0 && (
              <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("empty")}</p>
            )}
            {forks.length > 0 && (
              <ul className="space-y-1">
                {forks.map((fork) => (
                  <li key={fork.id}>
                    <button
                      type="button"
                      title={t("open")}
                      onClick={() => {
                        setOpen(false);
                        onOpen(fork);
                      }}
                      className="hover:bg-accent flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left"
                    >
                      <GitBranch
                        className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0"
                        aria-hidden
                      />
                      <span className="flex min-w-0 flex-1 flex-col gap-1">
                        <span className="flex min-w-0 items-center gap-2">
                          <span className="min-w-0 flex-1 truncate text-sm">
                            {fork.title || tChat("untitledFork")}
                          </span>
                          {fork.is_archived && (
                            <span className="text-muted-foreground shrink-0 text-xs">
                              {t("archived")}
                            </span>
                          )}
                        </span>
                        <span className="text-muted-foreground text-xs">
                          {timeAgo(fork.updated_at ?? fork.created_at, tTime, locale)}
                        </span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {query.hasNextPage && (
              <div className="flex justify-center px-3 py-3">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={query.isFetchingNextPage}
                  onClick={() => void query.fetchNextPage()}
                >
                  {query.isFetchingNextPage ? t("loading") : t("loadMore")}
                </Button>
              </div>
            )}
          </div>
          <div className="border-t p-3">
            <Button
              type="button"
              className="w-full"
              disabled={creating || creatingMessageId !== null}
              onClick={() => void create()}
            >
              <GitBranch className="h-4 w-4" aria-hidden />
              {creating || creatingMessageId !== null ? t("loading") : t("start")}
            </Button>
            {createFailed && (
              <p role="alert" className="text-destructive px-2 py-2 text-center text-sm">
                {t("createFailed")}
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
