"use client";

import { useId, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useRoomLeadPolicy, useRoomRoutingLists } from "@/hooks/use-room-routing";
import { useTenantId } from "@/hooks/use-organizations";
import { useAuthStore } from "@/stores";
import type { RoomLeadPolicy } from "@/types/room-routing";
import { RoomLeadPolicyDialog } from "./room-lead-policy-dialog";
import { RoomCanonicalTaskCard, RoomProposalCard } from "./room-routing-cards";

interface RoomRoutingPanelProps {
  conversationId: string;
  readOnly: boolean;
  threadRootMessageId?: string | null;
  onOpenThread?: (root: string) => void;
}

export function RoomRoutingPanel(props: RoomRoutingPanelProps) {
  const account = useAuthStore((state) => state.user?.id);
  const tenant = useTenantId();
  // Local selections and uncertain decisions cannot move to another audience.
  return (
    <RoutingContent
      key={JSON.stringify([
        account,
        tenant,
        props.conversationId,
        props.threadRootMessageId ?? null,
      ])}
      {...props}
    />
  );
}

function RoutingContent({
  conversationId,
  readOnly,
  threadRootMessageId = null,
  onOpenThread,
}: RoomRoutingPanelProps) {
  const t = useTranslations("chat.roomRouting");
  const id = useId();
  const policy = useRoomLeadPolicy(conversationId);
  const { proposals, tasks, proposalItems, taskItems } = useRoomRoutingLists(
    conversationId,
    threadRootMessageId,
  );
  const [expanded, setExpanded] = useState(false);
  const [opened, setOpened] = useState(false);
  const [editing, setEditing] = useState<RoomLeadPolicy | null>(null);
  const visibleProposals = (policy.data ? proposalItems : []).filter(
    (item) =>
      item.conversation_id === conversationId &&
      (threadRootMessageId === null || item.thread_root_message_id === threadRootMessageId),
  );
  const visibleTasks = (policy.data ? taskItems : []).filter(
    (item) => threadRootMessageId === null || item.thread_root_message_id === threadRootMessageId,
  );
  const Icon = expanded ? ChevronDown : ChevronRight;
  return (
    <section className="mb-4 min-w-0 rounded-xl border" data-tour="chat-room-routing">
      <Button
        variant="ghost"
        className="h-auto min-h-11 w-full justify-start gap-2 px-3 py-2 text-left whitespace-normal"
        aria-expanded={expanded}
        aria-controls={id}
        onClick={() => {
          setOpened(true);
          setExpanded((value) => !value);
        }}
      >
        <Icon className="size-4 shrink-0" aria-hidden />
        <span className="flex-1 text-sm font-medium">{t("title")}</span>
        {visibleProposals.some((item) => item.decision === "pending") && (
          <span className="text-muted-foreground text-xs">{t("reviewNeeded")}</span>
        )}
      </Button>
      <div
        id={id}
        hidden={!expanded}
        className="max-h-[60dvh] space-y-4 overflow-y-auto border-t p-3"
      >
        {opened && (
          <>
            {policy.isError ? (
              <div role="alert" className="space-y-2 text-sm">
                <p>{t("policyUnavailable")}</p>
                <Button size="sm" variant="outline" onClick={() => void policy.refetch()}>
                  {t("retryRead")}
                </Button>
              </div>
            ) : !policy.data ? (
              <p role="status" className="text-muted-foreground text-xs">
                {t("loading")}
              </p>
            ) : (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="min-w-0 text-sm break-words">
                    {policy.data.enabled
                      ? policy.data.lead
                        ? t("leadNamed", { name: policy.data.lead.name })
                        : t("agentUnavailable")
                      : t("disabled")}
                  </p>
                  {policy.data.can_edit && !readOnly && (
                    <Button size="sm" variant="outline" onClick={() => setEditing(policy.data!)}>
                      {t("configure")}
                    </Button>
                  )}
                </div>
                <p className="text-muted-foreground text-xs">{t("normalPosts")}</p>
                {policy.data.lead?.current === false && (
                  <p className="text-muted-foreground text-xs">{t("pinnedLeadHint")}</p>
                )}
              </div>
            )}
            {policy.data && (
              <>
                <div className="space-y-3">
                  <h2 className="text-sm font-semibold">{t("proposals")}</h2>
                  {proposals.isError ? (
                    <div role="alert" className="space-y-2 text-sm">
                      <p>{t("proposalsUnavailable")}</p>
                      <Button size="sm" variant="outline" onClick={() => void proposals.refetch()}>
                        {t("retryRead")}
                      </Button>
                    </div>
                  ) : !proposals.isFetchedAfterMount ? (
                    <p role="status" className="text-muted-foreground text-xs">
                      {t("loading")}
                    </p>
                  ) : visibleProposals.length === 0 ? (
                    <p className="text-muted-foreground text-xs">{t("noProposals")}</p>
                  ) : (
                    visibleProposals.map((proposal) => (
                      <RoomProposalCard
                        key={proposal.id}
                        proposal={proposal}
                        readOnly={readOnly}
                        onOpenThread={threadRootMessageId === null ? onOpenThread : undefined}
                      />
                    ))
                  )}
                  {proposals.hasNextPage && !proposals.isError && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={proposals.isFetchingNextPage}
                      onClick={() => void proposals.fetchNextPage()}
                    >
                      {t("moreProposals")}
                    </Button>
                  )}
                </div>
                <div className="space-y-3">
                  <h2 className="text-sm font-semibold">{t("tasks")}</h2>
                  {tasks.isError ? (
                    <div role="alert" className="space-y-2 text-sm">
                      <p>{t("tasksUnavailable")}</p>
                      <Button size="sm" variant="outline" onClick={() => void tasks.refetch()}>
                        {t("retryRead")}
                      </Button>
                    </div>
                  ) : !tasks.isFetchedAfterMount ? (
                    <p role="status" className="text-muted-foreground text-xs">
                      {t("loading")}
                    </p>
                  ) : visibleTasks.length === 0 ? (
                    <p className="text-muted-foreground text-xs">{t("noTasks")}</p>
                  ) : (
                    visibleTasks.map((task) => (
                      <RoomCanonicalTaskCard
                        key={task.id}
                        task={task}
                        onOpenThread={threadRootMessageId === null ? onOpenThread : undefined}
                      />
                    ))
                  )}
                  {tasks.hasNextPage && !tasks.isError && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={tasks.isFetchingNextPage}
                      onClick={() => void tasks.fetchNextPage()}
                    >
                      {t("moreTasks")}
                    </Button>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
      {editing && policy.data?.can_edit && !readOnly && (
        <RoomLeadPolicyDialog
          conversationId={conversationId}
          policy={editing}
          onClose={() => setEditing(null)}
        />
      )}
    </section>
  );
}
