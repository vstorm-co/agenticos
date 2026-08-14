"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Activity, ArrowLeft, ArrowRight, ExternalLink, MessageSquare, Play } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { RunStatusBadge } from "@/components/agents/status-badge";
import { SurfaceIcon, surfaceLabel } from "@/components/runs/surface-icon";
import { RunTimeline } from "@/components/runs/run-timeline";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { useAgent, useDelegatedRuns, usePermissions, useResumeRun, useRun } from "@/hooks";
import { useAuthStore } from "@/stores";
import { ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, formatRunDuration } from "@/lib/utils";
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
 * `prev`/`next` walk the agent's own history by start time, the ids resolved
 * server-side on this read - so stepping through a bad afternoon is arrows, not
 * trips back to the list.
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

  if (isLoading) return <LoadingState variant="skeleton-table" columns={6} rows={2} />;
  if (run === undefined) {
    // Absent once the wait is over means the request did not answer, and the two
    // reasons do not read the same. A run that is gone - or in another tenant,
    // which the API answers identically and on purpose - is a fact about the
    // link. Anything else is a fact about the request, and saying "no such run"
    // for a refused permission sends somebody looking for a run that is there.
    return error instanceof ApiError && error.status === 404 ? (
      <EmptyState icon={Activity} title={t("noSuchRun")} description={t("theRunNamedIn")} />
    ) : (
      <ErrorState title={t("runCouldNotBeRead")} />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
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
        {/* The agent's history, one step either way - resolved server-side on
            this read, disabled at the edges rather than absent so the timeline
            keeps its shape while somebody steps through it. */}
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
            disabled={run.prev_run_id == null}
            aria-label={t("previousRun")}
            onClick={() => run.prev_run_id != null && onFocusRun(run.prev_run_id)}
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={run.next_run_id == null}
            aria-label={t("nextRun")}
            onClick={() => run.next_run_id != null && onFocusRun(run.next_run_id)}
          >
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
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

      <section className="space-y-2">
        <h3 className="text-foreground text-sm font-semibold">{t("timeline")}</h3>
        <RunTimeline runId={runId} />
      </section>

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
