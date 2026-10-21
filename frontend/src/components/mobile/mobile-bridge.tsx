"use client";

import { useEffect, useEffectEvent, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";

import { useShellEvent } from "@/hooks/use-desktop";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { useApprovals, useRuns } from "@/hooks/use-runs";
import { useShell } from "@/hooks/use-shell";
import { argumentsPreview } from "@/lib/desktop/notices";
import { isMobileShell, reportShellFailure, SHELL_EVENTS } from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import {
  endActivity,
  planActivities,
  showActivity,
  takeActivityAction,
  type LiveActivity,
} from "@/lib/mobile/live-activities";
import { useAuthStore } from "@/stores";
import { Perm } from "@/types/permissions";

const APPROVALS_PATH = "/runs?tab=approvals";
/** How often the person's running runs are read; a run is long enough for this. */
const RUNNING_POLL_MS = 15_000;
/**
 * The most runs live at once. A lock screen holding a row per run is a list,
 * and a list belongs in the app; the newest few say "your agents are busy".
 */
const MAX_RUNS = 3;

/**
 * The console's half of the phone app, mounted once: what is live - the
 * person's own runs in flight, the approvals waiting for them - told to the app
 * to draw outside itself, and what a button there asked, acted on here.
 *
 * Every read is one a console page already makes, so the phone shows nothing the
 * console would not. A decision is made by this page's session, through the
 * request the queue's own buttons make; the app hands one over only once the
 * person is through its lock.
 */
export function MobileBridge() {
  const shell = useShell();
  return isMobileShell(shell) ? <Bridge /> : null;
}

function Bridge() {
  const t = useTranslations("mobile.activity");
  const router = useRouter();
  const { can } = usePermissions();
  const canDecide = can(Perm.approvalsDecide);
  const userId = useAuthStore((state) => state.user?.id);
  const { approvals, decide } = useApprovals({ enabled: canDecide });
  const { runs } = useRuns(undefined, {
    enabled: can(Perm.runsView) && userId !== undefined,
    statuses: ["running"],
    userId,
    refetchIntervalMs: RUNNING_POLL_MS,
  });
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });

  const live = useMemo<LiveActivity[]>(() => {
    const names = new Map(agents.map((agent) => [agent.id, agent.name]));
    const waiting = approvals.map((approval): LiveActivity => ({
      id: `approval:${approval.id}`,
      kind: "approval",
      title: t("approvalTitle", {
        agent: approval.agent_name ?? t("anAgent"),
        tool: approval.tool_id,
      }),
      body: argumentsPreview(approval.tool_args),
      path: APPROVALS_PATH,
      approvalId: approval.id,
      approveLabel: t("approve"),
      rejectLabel: t("reject"),
    }));
    const working = runs.slice(0, MAX_RUNS).map((run): LiveActivity => ({
      id: `run:${run.id}`,
      kind: "run",
      title: t("runTitle", { agent: names.get(run.agent_id) ?? t("anAgent") }),
      body: t("runBody"),
      path: `/runs?run=${encodeURIComponent(run.id)}`,
      ...(run.started_at ? { startedAt: Date.parse(run.started_at) } : {}),
    }));
    return [...waiting, ...working];
  }, [agents, approvals, runs, t]);

  const shown = useRef(new Map<string, string>());
  useEffect(() => {
    const { show, end } = planActivities(shown.current, live);
    for (const activity of show) {
      shown.current.set(activity.id, JSON.stringify(activity));
      showActivity(activity).catch((error: unknown) =>
        reportShellFailure("could not show a live activity", error),
      );
    }
    for (const id of end) {
      shown.current.delete(id);
      endActivity(id).catch((error: unknown) =>
        reportShellFailure("could not end a live activity", error),
      );
    }
  }, [live]);

  // Signed out, or the console gone: nothing it showed is live any more.
  useEffect(() => {
    const current = shown.current;
    return () => {
      for (const id of current.keys()) {
        endActivity(id).catch((error: unknown) =>
          reportShellFailure("could not end a live activity", error),
        );
      }
      current.clear();
    };
  }, []);

  const act = () => {
    takeActivityAction()
      .then((ask) => {
        if (ask?.kind === "open") router.push(ask.path);
        // Not gated on `canDecide`: on a cold start the permissions may not have
        // arrived yet, and a decision taken then would be dropped. The server
        // refuses one this person may not make, and the refusal is its toast.
        if (ask?.kind === "decide") decide.mutate({ id: ask.approval_id, approved: ask.approved });
      })
      .catch((error: unknown) => reportShellFailure("could not read an activity's action", error));
  };
  // A button pressed while the app was closed waits for this page to arrive.
  const actOnArrival = useEffectEvent(act);
  useEffect(() => actOnArrival(), []);
  useShellEvent(SHELL_EVENTS.activity, act);

  return null;
}
