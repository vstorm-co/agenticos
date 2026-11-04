"use client";
import { useEffect, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { useDesktopActiveRuns } from "@/hooks/use-desktop-active-runs";
import { useTenantId } from "@/hooks/use-organizations";
import { useDesktopLiveStore } from "@/stores/desktop-live-store";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { useApprovals } from "@/hooks/use-runs";
import { useAuthStore, useConversationStore } from "@/stores";
import { useWorkingStore } from "@/stores/working-store";
import { publishDesktopActivity, type DesktopActivityEntry } from "@/lib/desktop/readiness";
import { reportShellFailure } from "@/lib/desktop/shell";
import { Perm } from "@/types/permissions";

export function DesktopActivityBridge() {
  const t = useTranslations("desktop.activity");
  const tenant = useTenantId();
  const live = useDesktopLiveStore((s) => s.turns);
  const user = useAuthStore((s) => s.user?.id);
  const { can } = usePermissions();
  const { runs } = useDesktopActiveRuns();
  const { agents } = useAgents({ enabled: !!user && can(Perm.agentsView) });
  const { approvals } = useApprovals({ enabled: can(Perm.approvalsDecide) });
  const current = useConversationStore((s) => s.currentConversationId);
  const path = usePathname();
  const working = useWorkingStore((s) => s.since);
  const handed = useWorkingStore((s) => s.handedOff);
  const entries = useMemo((): DesktopActivityEntry[] => {
    const mine = runs
      .filter((run) => run.user_id === user)
      .slice(0, 20)
      .map((run): DesktopActivityEntry => ({
        id: run.conversation_id ?? run.id,
        title: t(
          run.status === "running"
            ? "running"
            : run.status === "awaiting_answer"
              ? "question"
              : "approval",
          { agent: agents.find((a) => a.id === run.agent_id)?.name ?? t("agent") },
        ),
        path: run.conversation_id ? `/chat?id=${run.conversation_id}` : `/runs/${run.id}`,
        stop_conversation:
          run.conversation_id && working[run.conversation_id] && !handed[run.conversation_id]
            ? run.conversation_id
            : null,
      }));
    const pending = approvals
      .filter((a) => a.status === "pending")
      .slice(0, 10)
      .map((a): DesktopActivityEntry => ({
        id: a.id,
        title: t("approval", { agent: a.agent_name ?? t("agent") }),
        path: "/runs?tab=approvals",
        stop_conversation: null,
      }));
    const merged = new Map(mine.map((entry) => [entry.id, entry]));
    for (const turn of Object.values(live)) {
      const existing = merged.get(turn.conversation);
      merged.set(turn.conversation, {
        id: turn.conversation,
        title: t(turn.state, { agent: t("agent") }),
        path: `/chat?id=${turn.conversation}`,
        stop_conversation: turn.canStop ? turn.conversation : (existing?.stop_conversation ?? null),
        question: turn.state === "question",
      });
    }
    return [...merged.values(), ...pending].slice(0, 30);
  }, [runs, agents, user, approvals, t, working, handed, live]);
  useEffect(() => {
    void publishDesktopActivity(entries, path.endsWith("/chat") ? current : null, {
      user,
      organization: tenant,
    }).catch((e: unknown) => reportShellFailure("publishing desktop activity", e));
  }, [entries, current, path, user, tenant]);
  useEffect(
    () => () => {
      void publishDesktopActivity([], null).catch((e: unknown) =>
        reportShellFailure("clearing desktop activity", e),
      );
    },
    [],
  );
  return null;
}
