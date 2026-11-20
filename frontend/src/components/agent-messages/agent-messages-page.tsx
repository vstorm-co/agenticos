"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Lock, MessagesSquare, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/states";
import { Button, Card, ListCard, PAGE_SIZE } from "@/components/ui";
import { useAgentMessageThreads, useMarkAgentMessageThreadRead, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";
import { MessageThread } from "./message-thread";
import { NewMessageDialog } from "./new-message-dialog";
import { ThreadList } from "./thread-list";

/**
 * Agent messages: the threads between two agents, most recently active
 * first, with the open thread beside them. Reading needs `agents:run` on
 * either agent in a thread; the page itself is gated on `agents:run`.
 */
export function AgentMessagesPage() {
  const t = useTranslations("agentMessages");
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const { threads, total, isLoading, error, refetch } = useAgentMessageThreads(0, PAGE_SIZE);
  const { markRead } = useMarkAgentMessageThreadRead();
  const markReadMutate = markRead.mutate;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const selected = threads.find((thread) => thread.id === selectedId) ?? threads[0] ?? null;

  // Opening a thread that waits on the reader marks it read. `mutate` is
  // stable, so the effect fires once per thread picked, not on every render
  // while the row still reads unread before the refetch lands.
  useEffect(() => {
    if (selected?.unread) markReadMutate(selected.id);
  }, [selected?.id, selected?.unread, markReadMutate]);

  const header = (
    <PageHeader
      title={t("title")}
      description={t("description")}
      actions={
        can(Perm.agentsRun) ? (
          <Button data-tour="agent-messages-new" onClick={() => setDialogOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("newMessage")}
          </Button>
        ) : undefined
      }
    />
  );

  if (!isLoadingPermissions && !can(Perm.agentsRun)) {
    return (
      <div className="flex flex-1 flex-col space-y-4">
        {header}
        <EmptyState icon={Lock} title={t("cannotSee")} description={t("askForAccess")} />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col space-y-4">
      {header}
      <div className="flex min-h-0 flex-1 flex-col gap-4 lg:flex-row">
        <ListCard
          fill
          namedByPage
          title={t("title")}
          counted={error || isLoading ? null : t("threadCount", { count: total })}
          contentClassName="p-0"
          className="w-full shrink-0 lg:w-80"
          data-tour="agent-messages-list"
        >
          <ThreadList
            threads={threads}
            selectedId={selected?.id ?? null}
            onSelect={setSelectedId}
            isLoading={isLoading}
            error={error}
            refetch={() => void refetch()}
          />
        </ListCard>
        <Card className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          {selected ? (
            <MessageThread thread={selected} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-5">
              <EmptyState
                icon={MessagesSquare}
                title={t("selectThread.title")}
                description={t("selectThread.description")}
              />
            </div>
          )}
        </Card>
      </div>

      <NewMessageDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onSent={(threadId) => setSelectedId(threadId)}
      />
    </div>
  );
}
