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
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";
import type { Trigger } from "@/types/triggers";

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
 * `pendingSince` is the moment "Run now" was pressed, or null. A fire is
 * dispatched after the request commits, so for a second there is no row for it:
 * the list shows a starting row and polls until one appears.
 */
export function TriggerRunsView({
  trigger,
  pendingSince,
}: {
  trigger: Trigger;
  pendingSince: number | null;
}) {
  const t = useTranslations("triggers");
  const [page, setPage] = useState(0);
  const conversationId = trigger.conversation_id;

  const { runs, total, isLoading, error } = useRuns(undefined, {
    enabled: conversationId !== null,
    conversationId: conversationId ?? undefined,
    skip: page * PAGE,
    // While a fire is in flight the row for it does not exist yet; once it does,
    // its status is still `running` for as long as the agent takes.
    ...(pendingSince !== null ? { refetchIntervalMs: POLL_WHILE_WAITING_MS } : {}),
  });

  // A trigger that has never fired has no run-log conversation either, so there
  // is nothing to poll but the trigger itself: its `conversation_id` appears with
  // the first fire, at which point the listing above takes over.
  const queryClient = useQueryClient();
  useEffect(() => {
    if (pendingSince === null) return;
    const timer = setInterval(() => {
      void queryClient.invalidateQueries({ queryKey: qk.triggers.all() });
      void queryClient.invalidateQueries({ queryKey: qk.runs.all() });
    }, POLL_WHILE_WAITING_MS);
    return () => clearInterval(timer);
  }, [pendingSince, queryClient]);

  if (conversationId !== null && isLoading) {
    return <LoadingState variant="skeleton-table" columns={1} rows={4} className="m-5" />;
  }
  if (conversationId !== null && error !== null) {
    return <ErrorState title={t("runsCouldNotBeRead")} className="m-5" />;
  }

  // A row for the fire that has been dispatched and has not recorded itself yet:
  // without it, pressing Run now on a trigger with no history answers with "not
  // run yet" for a few seconds, which is the opposite of what just happened.
  const starting = pendingSince !== null && !runs.some((run) => run.status === "running");

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

/** One fire: when it ran, how it went, what it cost, and a way into it. */
function FireRow({ run }: { run: AgentRun }) {
  const t = useTranslations("triggers");
  const locale = useLocale();
  const failed = run.status === "failed" || run.status === "budget_exceeded";
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
 * Opaque, unlike the navigation sheets that share the primitive: `glass-strong`
 * is right for a panel somebody glances at over a page they still want to see,
 * and wrong for one they read - behind translucency the rows of the list
 * underneath print through the middle of it. The same argument the dialog
 * primitive already carries for a centred modal.
 */
export function TriggerRunsSheet({
  trigger,
  pendingSince,
  open,
  onOpenChange,
}: {
  trigger: Trigger;
  pendingSince: number | null;
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
        {open && <TriggerRunsView trigger={trigger} pendingSince={pendingSince} />}
      </SheetContent>
    </Sheet>
  );
}
