"use client";

import { useEffect, useEffectEvent, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";

import { useShellEvent } from "@/hooks/use-desktop";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { useApprovals, useRuns, useSpend } from "@/hooks/use-runs";
import { useOrganizationList } from "@/hooks/use-organizations";
import { useOpenShared } from "@/hooks/use-open-shared";
import { useShell } from "@/hooks/use-shell";
import { argumentsPreview } from "@/lib/desktop/notices";
import {
  isMobileShell,
  reportShellFailure,
  SHELL_EVENTS,
  type ShellInfo,
} from "@/lib/desktop/shell";
import { useRouter } from "@/lib/locale-navigation";
import {
  endActivity,
  planActivities,
  showActivity,
  takeActivityAction,
  type LiveActivity,
} from "@/lib/mobile/live-activities";
import { updateWidget } from "@/lib/mobile/widget";
import { iphonePush, syncIphonePush } from "@/lib/mobile/apns";
import { phonePushStatus, syncPhonePush } from "@/lib/mobile/push";
import { recordSessionApp } from "@/lib/session-app";
import { useAuthStore, useComposerIntentStore, useOrgStore } from "@/stores";
import { useLiveCallStore } from "@/stores/live-call-store";
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
 * to draw outside itself; and what a button there or a home-screen shortcut
 * asked, acted on here.
 *
 * Every read is one a console page already makes, so the phone shows nothing the
 * console would not. A decision is made by this page's session, through the
 * request the queue's own buttons make; the app hands one over only once the
 * person is through its lock.
 */
export function MobileBridge() {
  const shell = useShell();
  return isMobileShell(shell) ? <Bridge shell={shell} /> : null;
}

function Bridge({ shell }: { shell: ShellInfo }) {
  const t = useTranslations("mobile.activity");
  const router = useRouter();
  const { can } = usePermissions();
  const canDecide = can(Perm.approvalsDecide);
  const userId = useAuthStore((state) => state.user?.id);
  const {
    approvals,
    total: waiting,
    isLoading: approvalsLoading,
    error: approvalsError,
    decide,
  } = useApprovals({ enabled: canDecide });
  const {
    runs,
    isLoading: runsLoading,
    error: runsError,
  } = useRuns(undefined, {
    enabled: can(Perm.runsView) && userId !== undefined,
    statuses: ["running", "awaiting_answer"],
    userId,
    refetchIntervalMs: RUNNING_POLL_MS,
  });
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });
  const call = useLiveCallStore((state) => state.call);
  const budgetLeft = useBudgetLeft(can(Perm.runsView));
  const requestIntent = useComposerIntentStore((state) => state.request);
  const openShared = useOpenShared();

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
    // An agent's question is the person's to answer, so it is drawn like an
    // approval - up front - and opens the conversation it was asked in.
    const asking = runs
      .filter((run) => run.status === "awaiting_answer")
      .map((run): LiveActivity => ({
        id: `question:${run.id}`,
        kind: "question",
        title: t("questionTitle", { agent: names.get(run.agent_id) ?? t("anAgent") }),
        body: t("questionBody"),
        path: run.conversation_id
          ? `/chat?id=${encodeURIComponent(run.conversation_id)}`
          : `/runs?run=${encodeURIComponent(run.id)}`,
      }));
    const working = runs
      .filter((run) => run.status === "running" && run.id !== call?.runId)
      .slice(0, MAX_RUNS)
      .map((run): LiveActivity => ({
        id: `run:${run.id}`,
        kind: "run",
        title: t("runTitle", { agent: names.get(run.agent_id) ?? t("anAgent") }),
        body: t("runBody"),
        path: `/runs?run=${encodeURIComponent(run.id)}`,
        ...(run.started_at ? { startedAt: Date.parse(run.started_at) } : {}),
      }));
    const calling: LiveActivity[] =
      call === null
        ? []
        : [
            {
              id: `call:${call.callId}`,
              kind: "call",
              title: t("callTitle", { agent: names.get(call.agentId) ?? t("anAgent") }),
              body: call.asking ? t("callAsking") : t("callBody"),
              path: call.conversationId
                ? `/chat?id=${encodeURIComponent(call.conversationId)}`
                : "/chat",
              startedAt: call.startedAt,
            },
          ];
    return [...calling, ...waiting, ...asking, ...working];
  }, [agents, approvals, runs, call, t]);

  // The sessions list names this app, not the webview's engine.
  useEffect(() => {
    recordSessionApp(shell).catch((error: unknown) =>
      reportShellFailure("could not tell the server which app this is", error),
    );
  }, [shell]);

  // A distributor - or APNs - can hand over a new address at any time; the
  // server is told the current one whenever the console arrives, as a
  // browser's is.
  useEffect(() => {
    const sync =
      shell.platform === "android"
        ? phonePushStatus().then(syncPhonePush)
        : iphonePush().then(syncIphonePush);
    sync.catch((error: unknown) => reportShellFailure("could not sync push", error));
  }, [shell]);

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

  // The widget's counts, once both are read: a zero before the first answer,
  // or in place of a failed one, would be kept on the home screen as a fact.
  // The widget keeps its last good counts, with the time they were counted.
  const counted = !approvalsLoading && !runsLoading && !approvalsError && !runsError;
  // The list holds questions too since they became live activities; the widget
  // counts what is actually running.
  const inFlight = runs.filter((run) => run.status === "running").length;
  useEffect(() => {
    if (!counted) return;
    updateWidget({ approvals: waiting, running: inFlight, budget_left: budgetLeft }).catch(
      (error: unknown) => reportShellFailure("could not update the widget", error),
    );
  }, [counted, waiting, inFlight, budgetLeft]);

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
        if (ask?.kind === "start") {
          requestIntent(ask.mode);
          router.push("/chat");
        }
      })
      .catch((error: unknown) => reportShellFailure("could not read an activity's action", error));
    openShared();
  };
  // A button pressed, or something shared, while the app was closed waits for
  // this page to arrive; one shared while it was open arrives as the app comes
  // back to the front, and one held by the lock when the lock lets go.
  const actOnArrival = useEffectEvent(act);
  useEffect(() => {
    actOnArrival();
    const onVisible = () => {
      if (document.visibilityState === "visible") actOnArrival();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  useShellEvent(SHELL_EVENTS.activity, act);

  return null;
}

/**
 * The share of the organization's monthly cap left, for the widget (#2305):
 * the figures the dashboard's budget card reads. `null` with no cap, or none
 * the person may read.
 */
function useBudgetLeft(enabled: boolean): number | null {
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const organizations = useOrganizationList();
  const { spend } = useSpend(30, { enabled });
  const organization = organizations.data?.find((candidate) => candidate.id === activeOrgId);
  const cap =
    organization?.monthly_budget_usd != null ? Number(organization.monthly_budget_usd) : null;
  if (!enabled || cap === null || cap <= 0 || spend === undefined) return null;
  const used = Number(spend.month_to_date_usd ?? 0);
  return Math.max(0, Math.min(100, Math.round(((cap - used) / cap) * 100)));
}
