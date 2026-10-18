"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  CornerLeftUp,
  ExternalLink,
  MessageSquare,
  Play,
  Wrench,
  X,
} from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { RunStatusBadge } from "@/components/agents/status-badge";
import { SurfaceIcon, surfaceLabel } from "@/components/runs/surface-icon";
import { RunManifest } from "@/components/runs/run-manifest";
import { RunTimeline } from "@/components/runs/run-timeline";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import {
  useAgent,
  useDelegatedRuns,
  usePermissions,
  usePrefetchRuns,
  useResumeRun,
  useRun,
} from "@/hooks";
import { useAuthStore } from "@/stores";
import { ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { cn, formatDateTime, formatRunDuration, timeAgo } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { AgentRun } from "@/types/runs";
import { RunTable } from "./run-table";

/**
 * One run as a trace: what went in, what the agent did, what it cost, and the
 * way to its neighbours - where a link from elsewhere lands.
 *
 * It exists because a delegated run is not in run history: the list is top-level
 * only, so that its count and cost column agree with the month-to-date figure
 * beside them. A delegation panel in a chat holds the run id its terminal frame
 * carried, and this is the surface that id reaches.
 *
 * The header answers the operator's first questions without a click - which
 * agent, on which model, through which surface, at what cost - and the timeline
 * below answers the second one: what actually happened, turn by turn, tool call
 * by tool call, with the ratings people left where they left them.
 *
 * `prev`/`next` walk the run's own conversation by start time, the ids resolved
 * server-side on this read - so stepping through a bad afternoon is arrows, not
 * trips back to the list, and the arrow keys do it without the mouse. A run with
 * no conversation behind it - an API call - has no neighbours, so its arrows
 * stay disabled.
 *
 * **A step holds what is on screen.** Each run is a query key of its own, so
 * without that an arrow press drops the whole view to a skeleton and rebuilds
 * it - on a surface whose purpose is reading several runs in a row. The
 * neighbours are prefetched on arrival, the header fades in on the new row, and
 * the timeline is left standing: two runs of one conversation are the same
 * turns, so what moves is the anchor, which glides.
 *
 * A refusal is said out loud rather than drawn as an empty table. Every other
 * page here renders its empty state when a query fails, which makes "this run
 * was deleted" and "the request answered 502" the same pixels.
 */
export function FocusedRun({
  runId,
  onFocusRun,
  onClose,
}: {
  runId: string;
  onFocusRun: (runId: string | null) => void;
  /**
   * Dismiss the surface holding this, where there is one to dismiss.
   *
   * Rendered in the controls row rather than floated over the header, because
   * floated it lands on the step arrows at exactly the widths the panel is most
   * often dragged to.
   */
  onClose?: () => void;
}) {
  const t = useTranslations("pages.runs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { can } = usePermissions();
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const { run, isLoading, error } = useRun(runId);
  const { runs: delegated } = useDelegatedRuns(runId);
  const resume = useResumeRun();
  // What is on screen is the answer being held, which during a step is the run
  // stepped away from. Nothing that navigates may act on it: its neighbours are
  // its own, so an arrow pressed twice quickly would otherwise walk back to
  // where it started.
  const settling = run !== undefined && run.id !== runId;
  const prevRunId = settling ? null : (run?.prev_run_id ?? null);
  const nextRunId = settling ? null : (run?.next_run_id ?? null);
  // Warmed on arrival, so the step itself is a cache hit rather than a request.
  usePrefetchRuns([prevRunId, nextRunId]);

  useEffect(() => {
    // The arrows on the keyboard, doing what the arrows on screen do. Reading a
    // bad afternoon is a sequence of runs, and reaching for the mouse between
    // each of them is the whole friction this view exists to remove.
    //
    // Ignored where the key means something else: a modifier is a browser
    // shortcut, a caret in a field is somebody typing rather than stepping, and
    // an arrow already answered by the control that has focus is that control's.
    // The tab strip is the one that bites - ArrowLeft and ArrowRight are how
    // Radix moves between Timeline and Input, and a window listener sits above
    // it, so stepping between tabs also stepped between runs.
    function step(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.defaultPrevented) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable ||
          ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
          // Anything focusable that reads an arrow of its own - a tab, a menu, a
          // slider, a listbox. Asked of the ancestors too, because focus lands on
          // the element carrying the role and a handler may be on its wrapper.
          target.closest(
            'button, a[href], [role="tab"], [role="button"], [role="menu"], [role="menuitem"], [role="listbox"], [role="option"], [role="slider"], [role="radiogroup"]',
          ) !== null)
      ) {
        return;
      }
      const to = event.key === "ArrowLeft" ? prevRunId : nextRunId;
      if (to === null) return;
      event.preventDefault();
      onFocusRun(to);
    }
    window.addEventListener("keydown", step);
    return () => window.removeEventListener("keydown", step);
  }, [prevRunId, nextRunId, onFocusRun]);

  // Before the wait, because holding the previous run's row means `isLoading` is
  // false while a failure for *this* one is already known - and the held row
  // would otherwise be drawn as though it were the answer to the id in the URL.
  if (error) {
    // The two reasons do not read the same. A run that is gone - or in another
    // tenant, which the API answers identically and on purpose - is a fact about
    // the link. Anything else is a fact about the request, and saying "no such
    // run" for a refused permission sends somebody looking for a run that is
    // there.
    return error instanceof ApiError && error.status === 404 ? (
      <EmptyState icon={Activity} title={t("noSuchRun")} description={t("theRunNamedIn")} />
    ) : (
      <ErrorState title={t("runCouldNotBeRead")} />
    );
  }
  if (isLoading || run === undefined) {
    return <LoadingState variant="skeleton-table" columns={6} rows={2} />;
  }

  return (
    // `Tabs` is the shell rather than a section of it, because the strip belongs
    // to the header that stays and the panels belong to the part that scrolls -
    // and Radix is happy for its list and its content to sit in different rows.
    <Tabs
      defaultValue="timeline"
      className="flex h-full min-h-0 flex-col gap-0"
      aria-busy={settling}
    >
      {/* Which run, what it cost and which view - held above the scroll. The
          answer to "what am I looking at" is the thing a reader most needs while
          they are deep in a transcript, and it was the first thing to leave.
          Keyed on the run, so it fades in on a step rather than mutating field
          by field; the panels below are deliberately *not* keyed, because two
          runs of one conversation share their turns and remounting would rebuild
          a list that was already correct. */}
      <div key={run.id} className="run-detail-in shrink-0 space-y-3 border-b px-4 pt-4 pb-0">
        {/* Who ran and how it ended on the first line, with the ways out of
            this run - step, resume, close - at its end; where it came from and
            on what model on the line under it. The steps used to take a row of
            their own between the two. */}
        <div className={cn("flex items-start gap-2", settling && "opacity-60")}>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
            {/* The agent's identity needs agents:view to resolve; without it the
              header simply starts at the status - never a request that 403s. */}
            {can(Perm.agentsView) && <AgentIdentity agentId={run.agent_id} />}
            <RunStatusBadge status={run.status} />
          </div>
          {/* The run's conversation, one step either way - resolved server-side
            on this read, disabled at the edges (and on a conversationless run)
            rather than absent so the timeline keeps its shape while somebody
            steps through it. */}
          <div className="flex shrink-0 items-center gap-0.5">
            {/* A parked run whose approvals were all decided is a run somebody
              still has to nudge: the resume endpoint is idempotent about the
              decision - a call still parked answers a refusal, not a second
              decision - so the button asks for approvals:decide, the same
              permission the endpoint carries. */}
            {run.status === "awaiting_approval" && can(Perm.approvalsDecide) && (
              <Button
                variant="outline"
                size="sm"
                className="mr-1"
                disabled={resume.isPending}
                onClick={() => resume.mutate(run.id)}
              >
                <Play className="h-4 w-4" aria-hidden />
                {t("resumeRun")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={prevRunId === null}
              aria-label={t("previousRun")}
              title={t("previousRun")}
              onClick={() => prevRunId !== null && onFocusRun(prevRunId)}
            >
              <ArrowLeft className="h-4 w-4" aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={nextRunId === null}
              aria-label={t("nextRun")}
              title={t("nextRun")}
              onClick={() => nextRunId !== null && onFocusRun(nextRunId)}
            >
              <ArrowRight className="h-4 w-4" aria-hidden />
            </Button>
            {onClose !== undefined && (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("closeRunDetail")}
                onClick={onClose}
              >
                <X className="h-4 w-4" aria-hidden />
              </Button>
            )}
          </div>
        </div>

        <div
          className={cn(
            "text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs",
            settling && "opacity-60",
          )}
        >
          <span className="flex items-center gap-1.5">
            <SurfaceIcon surface={run.surface} />
            {surfaceLabel(run.surface, t)}
          </span>
          <span className="flex items-center gap-1.5">
            {run.provider !== null && (
              <ProviderIcon provider={run.provider} className="h-3.5 w-3.5" />
            )}
            {run.model_label ?? "-"}
          </span>
          {run.started_at !== null && (
            <span title={formatDateTime(run.started_at, locale)}>
              {timeAgo(run.started_at, tTime, locale)}
            </span>
          )}
        </div>

        {/* The three numbers somebody opens a run to check, on one filled
            strip rather than four columns of capitals - a date there wrapped
            onto two lines and set the strip's height. */}
        <dl
          className={cn(
            "bg-muted/50 divide-foreground/[0.06] grid grid-cols-3 divide-x rounded-xl",
            settling && "opacity-60",
          )}
        >
          <Fact label={t("tokens")}>
            {run.input_tokens.toLocaleString(locale)}
            <span className="text-muted-foreground"> → </span>
            {run.output_tokens.toLocaleString(locale)}
          </Fact>
          <Fact label={t("cost")}>
            ${Number(run.cost_usd).toFixed(4)}
            {run.cost_is_partial && (
              <span className="text-muted-foreground" title={t("modelRunHadNo")}>
                {" +"}
              </span>
            )}
          </Fact>
          <Fact label={t("took")}>{formatRunDuration(run.started_at, run.ended_at)}</Fact>
        </dl>

        {!!run.tool_args_repaired && (
          <p className="text-muted-foreground flex items-center gap-1.5 text-xs">
            <Wrench className="size-3.5 shrink-0" aria-hidden />
            {t("toolArgsRepaired", { count: run.tool_args_repaired })}
          </p>
        )}

        {/* The input above includes the cache's share, priced apart from the rest:
            this is what reconciles a run with the provider's console (#2170). */}
        {!!(run.cache_read_tokens || run.cache_write_tokens) && (
          <p className="text-muted-foreground text-xs">
            {t("cacheSplit", {
              read: run.cache_read_tokens ?? 0,
              write: run.cache_write_tokens ?? 0,
            })}
          </p>
        )}

        {/* Hidden when it holds none of the three, rather than repeating all
            three conditions around it. */}
        <div className="flex flex-wrap items-center gap-1.5 empty:hidden">
          {run.parent_run_id !== null && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onFocusRun(run.parent_run_id)}
            >
              <CornerLeftUp className="h-3.5 w-3.5" aria-hidden />
              {t("openTheRunItCame")}
            </Button>
          )}
          {run.conversation_id !== null && run.user_id !== null && run.user_id === meId && (
            <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
              <Link href={`${ROUTES.CHAT}?id=${run.conversation_id}`}>
                <MessageSquare className="h-3.5 w-3.5" aria-hidden />
                {t("openTheChatBehind")}
              </Link>
            </Button>
          )}
          {/* The trace, where one can be read. The URL is this read's own field,
              resolved server-side because an agent may redirect its traces to a
              client's Logfire project - a link only when there is genuinely
              somewhere to land, never a guess from the id. */}
          {run.logfire_url != null && (
            <Button variant="outline" size="sm" className="h-7 text-xs" asChild>
              <a href={run.logfire_url} target="_blank" rel="noreferrer">
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                {t("openTheTraceInLogfire")}
              </a>
            </Button>
          )}
        </div>

        {/* Two questions, and they are genuinely different ones. The timeline is
            what happened - the thread, the turns, the tool calls, the files. The
            input is what the model was given before any of it, which is what a
            wrong answer is usually explained by and which nothing else in the
            product shows. Tabs rather than one long column, because the second
            question is asked after the first has failed to answer. */}
        <TabsList>
          <TabsTrigger value="timeline">{t("timeline")}</TabsTrigger>
          <TabsTrigger value="input" data-tour="run-detail-input">
            {t("whatWentIn")}
          </TabsTrigger>
        </TabsList>
      </div>

      {/* The one scrolling column. `min-h-0` is what makes it scroll rather than
          push the header off a flex parent that has no room to give. */}
      <div className="min-h-0 flex-1 scrollbar-thin space-y-6 overflow-y-auto px-4 py-4">
        <TabsContent value="timeline">
          <RunTimeline runId={runId} />
        </TabsContent>
        <TabsContent value="input">
          <RunManifest runId={runId} />
        </TabsContent>

        {delegated.length > 0 && (
          <section className="space-y-2">
            <h3 className="text-foreground text-sm font-semibold">{t("delegations")}</h3>
            <RunTable runs={[run as AgentRun, ...delegated]} />
            <p className="text-muted-foreground text-xs">
              {t("delegationsAlreadyCounted", { count: delegated.length })}
            </p>
          </section>
        )}
      </div>
    </Tabs>
  );
}

/** The agent's face and name, linking to its Builder page. */
function AgentIdentity({ agentId }: { agentId: string }) {
  const t = useTranslations("pages.runs");
  const { agent } = useAgent(agentId);
  if (!agent) return null;
  return (
    <Link
      href={`${ROUTES.AGENTS}/${agentId}`}
      className="flex items-center gap-2 text-sm font-medium hover:underline"
      aria-label={t("openTheAgent")}
    >
      <span aria-hidden>
        <AgentAvatar
          agentId={agentId}
          slug={agent.slug}
          hasAvatar={agent.has_avatar ?? false}
          size="sm"
        />
      </span>
      {agent.name}
    </Link>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-0.5 px-3 py-2.5">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-foreground truncate text-sm font-medium tabular-nums">{children}</dd>
    </div>
  );
}
