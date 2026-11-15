"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { useRoomActions } from "@/hooks/use-room";
import { getErrorMessage } from "@/lib/api-error";
import Link from "next/link";
import { ROUTES } from "@/lib/constants";
import { useAuthStore, useChatStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { Agent } from "@/types/agents";
import type { RoomAgentRequest } from "@/types/room";

const ACTIVE = new Set(["queued", "running", "awaiting_approval", "awaiting_answer"]);

export function TeamRoomQueue({
  conversationId,
  requests,
  agents,
  canPost,
}: {
  conversationId: string;
  requests: readonly RoomAgentRequest[];
  agents: readonly Agent[];
  canPost: boolean;
}) {
  const t = useTranslations("chat.teamRoom");
  const tErrors = useTranslations("errors");
  const me = useAuthStore((state) => state.user?.id);
  const messages = useChatStore((state) => state.messages);
  const { can } = usePermissions();
  const { cancel, isCurrent } = useRoomActions(conversationId);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const active = requests.filter((request) => ACTIVE.has(request.status));
  const recent = requests.filter((request) => !ACTIVE.has(request.status)).slice(0, 3);
  const shown = [...active, ...recent];

  async function cancelQueued(id: string) {
    setCancelling(id);
    try {
      await cancel(id);
    } catch (error) {
      if (isCurrent()) toast.error(getErrorMessage(error, tErrors, t("cancelFailed")));
    } finally {
      if (isCurrent()) setCancelling(null);
    }
  }

  if (shown.length === 0) return null;
  return (
    <details className="border-border/60 mb-2 rounded-xl border px-3 py-2" open={active.length > 0}>
      <summary className="cursor-pointer text-xs font-medium">
        {t("queueTitle", { count: active.length })}
      </summary>
      <ol className="mt-2 max-h-48 space-y-2 overflow-y-auto" aria-label={t("requests")}>
        {shown.map((request) => {
          const agent = agents.find((item) => item.id === request.agent_id);
          const sender = messages.find((message) => message.id === request.message_id)?.sender;
          const requester =
            request.requester_id === me ? t("you") : (sender?.name ?? t("teammate"));
          return (
            <li key={request.id} className="flex items-start gap-2 text-xs">
              <div className="min-w-0 flex-1">
                <p className="truncate">
                  {t("requestedBy", { agent: agent?.name ?? t("agent"), name: requester })}
                </p>
                <p className="text-muted-foreground" role="status">
                  {t(`status.${request.status}`)}
                </p>
                {request.error && <p className="text-destructive line-clamp-2">{request.error}</p>}
              </div>
              {request.run_id && can(Perm.runsView) && (
                <Link
                  className="shrink-0 underline underline-offset-2"
                  href={`${ROUTES.RUNS}?run=${request.run_id}`}
                >
                  {t("viewRun")}
                </Link>
              )}
              {canPost && request.status === "queued" && request.requester_id === me && (
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 px-2 text-xs"
                  disabled={cancelling !== null}
                  onClick={() => void cancelQueued(request.id)}
                >
                  {t("cancel")}
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </details>
  );
}
