"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, CheckCircle2, Loader2, PlayCircle, XCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Pager,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui";
import { useRuns } from "@/hooks";
import { useTriggerAttempts } from "@/hooks/use-triggers";
import { useStopParkedRun } from "@/hooks/use-stop-parked-run";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";
import type { PendingTriggerFire, Trigger, TriggerAttemptList } from "@/types/triggers";

const POLL_WHILE_WAITING_MS = 3000;
/** What one page of fires holds. The server's own ceiling for a run listing. */
const PAGE = 50;

/**
 * Every time a trigger has fired: when, how it went, and a way into the run.
 *
 * **A list of runs, not a transcript.** It was the chat's own `MessageList` over
 * the run-log conversation, which reads well for one fire and badly for forty
 * identical ones: the prompt is the same every time, so the only thing
 * distinguishing two fires is the reply, and a failed run's half-answer looks
 * exactly like a complete one. There was also nowhere to go from it - the run
 * detail, with the model's requests, the tools and the cost, is where somebody
 * asking "why did this fail" is actually headed.
 *
 * Read through `GET /runs?conversation_id=`: every fire of one trigger appends to
 * a single run-log conversation, so that conversation *is* the trigger's identity
 * in the run history. Which is also what gives each row a status, a duration and
 * a cost the transcript could not - and a link to `/runs?run=<id>`.
 *
 * `pendingFire` identifies the history before "Run now", or is null. A fire is
 * dispatched after the request commits, so for a second there is no row for it:
 * the list shows a starting row and polls until one appears.
 */
export function TriggerRunsView({
  trigger,
  pendingFire,
}: {
  trigger: Trigger;
  pendingFire: PendingTriggerFire | null;
}) {
  const t = useTranslations("triggers");
  const locale = useLocale();
  const [page, setPage] = useState(0);
  const [lastPendingFire, setLastPendingFire] = useState(pendingFire);
  if (lastPendingFire !== pendingFire) {
    setLastPendingFire(pendingFire);
    if (pendingFire !== null) setPage(0);
  }
  const [settledFire, setSettledFire] = useState<PendingTriggerFire | null>(null);
  const settled = pendingFire !== null && settledFire === pendingFire;
  const query = useTriggerAttempts(trigger, page, pendingFire !== null && !settled);
  const attempts = query.data;
  const latestAttemptId = page === 0 ? attempts?.items[0]?.id : undefined;
  if (
    !query.isFetching &&
    !query.error &&
    pendingFire !== null &&
    settledFire !== pendingFire &&
    latestAttemptId &&
    latestAttemptId !== pendingFire.previousAttemptId
  ) {
    setSettledFire(pendingFire);
  }
  return (
    <div className="flex h-full min-h-0 flex-col">
      {query.error ? (
        <ErrorState
          title={t("attemptsError")}
          className="m-5"
          cta={{ label: t("attemptsRetry"), onClick: () => void query.refetch() }}
        />
      ) : attempts && attempts.total > 0 ? (
        <AttemptHistory attempts={attempts} page={page} onPage={setPage} locale={locale} />
      ) : null}
      <div className="min-h-0 flex-1">
        <RunHistory
          trigger={trigger}
          pendingFire={settled ? null : pendingFire}
          onSettled={setSettledFire}
        />
      </div>
    </div>
  );
}

function AttemptHistory({
  attempts,
  page,
  onPage,
  locale,
}: {
  attempts: TriggerAttemptList;
  page: number;
  onPage: (page: number) => void;
  locale: string;
}) {
  const t = useTranslations("triggers");
  return (
    <section className="border-border max-h-64 shrink-0 overflow-y-auto border-b px-5 py-3">
      <h3 className="text-sm font-medium">{t("attemptsTitle")}</h3>
      <p className="text-muted-foreground mt-1 text-xs">{t("attemptsHint")}</p>
      <ul className="mt-2 space-y-3" aria-live="polite" aria-relevant="additions">
        {attempts.items.map((attempt) => (
          <li key={attempt.id} className="flex items-start gap-2 text-sm">
            <XCircle className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden />
            <div className="min-w-0">
              <p>
                {t(`attemptStatus.${attempt.status}`)} ·{" "}
                <time dateTime={attempt.occurred_at}>
                  {new Date(attempt.occurred_at).toLocaleString(locale, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </time>
              </p>
              <p className="text-muted-foreground text-xs">{t(`attemptStage.${attempt.stage}`)}</p>
              <p className="mt-1 text-xs break-words">{t(`attemptReason.${attempt.reason}`)}</p>
            </div>
          </li>
        ))}
      </ul>
      {attempts.total > 10 && (
        <div role="group" aria-label={t("attemptsTitle")} className="mt-2">
          <Pager
            page={page}
            pageCount={Math.ceil(attempts.total / 10)}
            matched={attempts.total}
            total={attempts.total}
            onPage={onPage}
            counted={t("attemptCount", { count: attempts.total })}
          />
        </div>
      )}
    </section>
  );
}

function RunHistory({
  trigger,
  pendingFire,
  onSettled,
}: {
  trigger: Trigger;
  pendingFire: PendingTriggerFire | null;
  onSettled: (fire: PendingTriggerFire) => void;
}) {
  const t = useTranslations("triggers");
  const [page, setPage] = useState(0);
  const conversationId = trigger.conversation_id;

  const { runs, total, isLoading, isFetching, error } = useRuns(undefined, {
    enabled: conversationId !== null,
    conversationId: conversationId ?? undefined,
    skip: page * PAGE,
    // Poll until a new history identity records the dispatched fire.
    ...(pendingFire !== null ? { refetchIntervalMs: POLL_WHILE_WAITING_MS } : {}),
  });
  const latestRunId = page === 0 ? runs[0]?.id : undefined;
  const recorded =
    !isFetching &&
    !error &&
    pendingFire !== null &&
    latestRunId !== undefined &&
    latestRunId !== pendingFire.previousRunId;
  useEffect(() => {
    if (recorded && pendingFire !== null) onSettled(pendingFire);
  }, [onSettled, pendingFire, recorded]);

  // A trigger that has never fired has no run-log conversation either, so there
  // is nothing to poll but the trigger itself: its `conversation_id` appears with
  // the first fire, at which point the listing above takes over.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (pendingFire === null) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: qk.triggers.all() });
      void queryClient.invalidateQueries({ queryKey: qk.runs.all() });
    }, POLL_WHILE_WAITING_MS);
    return () => clearInterval(timer);
  }, [pendingFire, queryClient]);

  if (conversationId !== null && isLoading) {
    return <LoadingState variant="skeleton-table" columns={1} rows={4} className="m-5" />;
  }
  if (conversationId !== null && error !== null) {
    return <ErrorState title={t("runsCouldNotBeRead")} className="m-5" />;
  }

  // A row for the fire that has been dispatched and has not recorded itself yet:
  // without it, pressing Run now on a trigger with no history answers with "not
  // run yet" for a few seconds, which is the opposite of what just happened.
  const starting = pendingFire !== null && !recorded;

  if (runs.length === 0 && !starting) {
    return <p className="text-muted-foreground p-5 text-sm">{t("noMessagesDescription")}</p>;
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ul className="min-h-0 flex-1 divide-y overflow-y-auto">
        {starting && (
          <li className="text-muted-foreground flex items-center gap-2 px-5 py-3 text-sm">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t("fireStarting")}
          </li>
        )}
        {runs.map((run) => (
          <FireRow key={run.id} run={run} />
        ))}
      </ul>
      <div className="border-border border-t px-5 py-3">
        <Pager
          page={page}
          pageCount={Math.max(1, Math.ceil(total / PAGE))}
          matched={total}
          total={total}
          onPage={setPage}
          counted={t("fireCount", { count: total })}
        />
      </div>
    </div>
  );
}

const STOPPED = new Set<AgentRun["status"]>([
  "failed",
  "budget_exceeded",
  "guardrail_blocked",
  "loop_stopped",
]);

/** One fire: when it ran, how it went, what it cost, and a way into it. */
function FireRow({ run }: { run: AgentRun }) {
  const t = useTranslations("triggers");
  const { canStop, stop } = useStopParkedRun(
    run.id,
    run.status === "awaiting_approval" || run.status === "awaiting_answer",
  );
  const locale = useLocale();
  // Every way a run ends without finishing its work: the run view is where "why" is.
  const failed = STOPPED.has(run.status);
  const done = run.status === "completed";
  const Mark = failed ? XCircle : done ? CheckCircle2 : PlayCircle;

  return (
    <li className="flex items-center gap-3 px-5 py-3 text-sm">
      <Mark
        className={cn(
          "h-4 w-4 shrink-0",
          failed ? "text-destructive" : done ? "text-success" : "text-muted-foreground",
        )}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <p className="truncate">
          {run.started_at === null ? (
            t(`fireStatus.${run.status}`)
          ) : (
            <time dateTime={run.started_at} className="tabular-nums">
              {new Date(run.started_at).toLocaleString(locale, {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </time>
          )}
        </p>
        <p className="text-muted-foreground truncate text-xs">
          {t("fireSummary", {
            status: t(`fireStatus.${run.status}`),
            cost: run.cost_usd,
          })}
        </p>
      </div>
      {canStop && (
        <Button variant="outline" size="sm" disabled={stop.isPending} onClick={() => stop.mutate()}>
          {t("stopWaitingRun")}
        </Button>
      )}
      {/* Into the run itself, which is where "why did this fail" is answered -
          the requests, the tools and what each turn cost. */}
      <Button variant="ghost" size="sm" asChild>
        <Link href={`${ROUTES.RUNS}?run=${run.id}`}>
          {t("openRun")}
          <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
        </Link>
      </Button>
    </li>
  );
}

/**
 * The runs list in a right-hand drawer, opened from a trigger row.
 *
 * Opaque, unlike the navigation sheets that share the primitive: `panel-strong`
 * is right for a panel somebody glances at over a page they still want to see,
 * and wrong for one they read - behind translucency the rows of the list
 * underneath print through the middle of it. The same argument the dialog
 * primitive already carries for a centred modal.
 */
export function TriggerRunsSheet({
  trigger,
  pendingFire,
  open,
  onOpenChange,
}: {
  trigger: Trigger;
  pendingFire: PendingTriggerFire | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="bg-background w-full sm:max-w-xl">
        <SheetHeader className="px-5">
          <SheetTitle className="text-sm">
            {trigger.name ?? trigger.agent_name ?? t("runsTitle")}
          </SheetTitle>
          <SheetClose onClick={() => onOpenChange(false)} />
        </SheetHeader>
        {open && <TriggerRunsView trigger={trigger} pendingFire={pendingFire} />}
      </SheetContent>
    </Sheet>
  );
}
