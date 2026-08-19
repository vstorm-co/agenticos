"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Activity, ArrowLeft, ArrowRight, ExternalLink, MessageSquare, Play } from "lucide-react";

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
import { cn, formatDateTime, formatRunDuration } from "@/lib/utils";
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
}: {
  runId: string;
  onFocusRun: (runId: string | null) => void;
}) {
  const t = useTranslations("pages.runs");
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
    // shortcut, and a caret in a field is somebody typing rather than stepping.
    function step(event: KeyboardEvent) {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName))
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
    <div className="space-y-6" aria-busy={settling}>
      {/* Keyed on the run, so the header and its figures fade in on a step
          rather than mutating field by field. The timeline below is deliberately
          *not* keyed: two runs of one conversation share their turns, so
          remounting it would rebuild a list that was already correct and throw
          away the scroll position the anchor is about to glide to. */}
      <div
        key={run.id}
        className={cn(
          "run-detail-in flex flex-wrap items-start justify-between gap-3",
          settling && "opacity-60",
        )}
      >
        <div className="flex flex-wrap items-center gap-3">
          {/* The agent's identity needs agents:view to resolve; without it the
              header simply starts at the status - never a request that 403s. */}
          {can(Perm.agentsView) && <AgentIdentity agentId={run.agent_id} />}
          <RunStatusBadge status={run.status} />
          <span className="text-muted-foreground flex items-center gap-1.5 text-sm">
            <SurfaceIcon surface={run.surface} />
            {surfaceLabel(run.surface, t)}
          </span>
          <span className="flex items-center gap-1.5 font-mono text-xs">
            {run.provider !== null && (
              <ProviderIcon provider={run.provider} className="h-3.5 w-3.5" />
            )}
            {run.model_label ?? "-"}
          </span>
        </div>
        {/* The run's conversation, one step either way - resolved server-side
            on this read, disabled at the edges (and on a conversationless run)
            rather than absent so the timeline keeps its shape while somebody
            steps through it. */}
        <div className="flex items-center gap-1">
          {/* A parked run whose approvals were all decided is a run somebody
              still has to nudge: the resume endpoint is idempotent about the
              decision - a call still parked answers a refusal, not a second
              decision - so the button asks for approvals:decide, the same
              permission the endpoint carries. */}
          {run.status === "awaiting_approval" && can(Perm.approvalsDecide) && (
            <Button
              variant="outline"
              size="sm"
              disabled={resume.isPending}
              onClick={() => resume.mutate(run.id)}
            >
              <Play className="h-4 w-4" aria-hidden />
              {t("resumeRun")}
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={prevRunId === null}
            aria-label={t("previousRun")}
            onClick={() => prevRunId !== null && onFocusRun(prevRunId)}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={nextRunId === null}
            aria-label={t("nextRun")}
            onClick={() => nextRunId !== null && onFocusRun(nextRunId)}
          >
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>

      <dl
        key={`facts-${run.id}`}
        className={cn(
          "run-detail-in grid grid-cols-2 gap-3 sm:grid-cols-4",
          settling && "opacity-60",
        )}
      >
        <Fact label={t("tokens")}>
          <span className="font-mono tabular-nums">
            {run.input_tokens} → {run.output_tokens}
          </span>
        </Fact>
        <Fact label={t("cost")}>
          <span className="font-mono tabular-nums">
            ${Number(run.cost_usd).toFixed(4)}
            {run.cost_is_partial && (
              <span className="text-muted-foreground" title={t("modelRunHadNo")}>
                {" +"}
              </span>
            )}
          </span>
        </Fact>
        <Fact label={t("took")}>
          <span className="font-mono tabular-nums">
            {formatRunDuration(run.started_at, run.ended_at)}
          </span>
        </Fact>
        <Fact label={t("started")}>
          {run.started_at === null ? "-" : formatDateTime(run.started_at, locale)}
        </Fact>
      </dl>

      <div className="flex flex-wrap items-center gap-4 text-xs">
        {run.parent_run_id !== null && (
          <button
            type="button"
            onClick={() => onFocusRun(run.parent_run_id)}
            className="text-muted-foreground underline underline-offset-4"
          >
            {t("openTheRunItCame")}
          </button>
        )}
        {run.conversation_id !== null && run.user_id !== null && run.user_id === meId && (
          <Link
            href={`${ROUTES.CHAT}?id=${run.conversation_id}`}
            className="text-muted-foreground inline-flex items-center gap-1 underline underline-offset-4"
          >
            <MessageSquare className="h-3 w-3" aria-hidden />
            {t("openTheChatBehind")}
          </Link>
        )}
        {/* The trace, where one can be read. The URL is this read's own field,
            resolved server-side because an agent may redirect its traces to a
            client's Logfire project - a link only when there is genuinely
            somewhere to land, never a guess from the id. */}
        {run.logfire_url != null && (
          <a
            href={run.logfire_url}
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground inline-flex items-center gap-1 underline underline-offset-4"
          >
            <ExternalLink className="h-3 w-3" aria-hidden />
            {t("openTheTraceInLogfire")}
          </a>
        )}
      </div>

      {/* Two questions, and they are genuinely different ones. The timeline is
          what happened - the thread, the turns, the tool calls, the files. The
          input is what the model was given before any of it, which is what a
          wrong answer is usually explained by and which nothing else in the
          product shows. Tabs rather than one long column, because the second
          question is asked after the first has failed to answer. */}
      <Tabs defaultValue="timeline">
        <TabsList>
          <TabsTrigger value="timeline">{t("timeline")}</TabsTrigger>
          <TabsTrigger value="input" data-tour="run-detail-input">
            {t("whatWentIn")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="timeline">
          <RunTimeline runId={runId} />
        </TabsContent>
        <TabsContent value="input">
          <RunManifest runId={runId} />
        </TabsContent>
      </Tabs>

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
          name={agent.name}
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
    <div className="space-y-0.5">
      <dt className="text-muted-foreground text-xs tracking-wide uppercase">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}
