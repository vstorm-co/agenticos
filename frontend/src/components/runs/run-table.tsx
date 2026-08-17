"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { MessageSquare, ThumbsDown } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { RunStatusBadge } from "@/components/agents/status-badge";
import { displayName, type IdentifiedMember } from "@/components/orgs/member-identity";
import { SurfaceIcon, surfaceLabel } from "@/components/runs/surface-icon";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { Badge, DataTable, EntityAvatar, type Column } from "@/components/ui";
import { useAuthStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, formatRunDuration, timeAgo } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";

/** The orders `GET /runs` offers, matching `RunOrder` on the backend. */
export type RunSortKey = "started_at" | "duration" | "cost" | "tokens";
export interface RunSort {
  by: RunSortKey;
  dir: "asc" | "desc";
}

/**
 * Run history as rows, wherever they came from.
 *
 * One table for the top level and for one run's delegations, because a row is a
 * row - what differs is which rows were asked for, and that is the caller's
 * sentence to write. The one thing the table itself must never do is let the two
 * kinds look identical: a delegated row's cost is *already inside* its parent's,
 * so a page that mixes them silently has a cost column nobody can add up. That
 * is the bug this badge exists for, next to a month-to-date figure that counts
 * each parent once.
 *
 * `sort`/`onSort` turn the Started, Took and Cost headers into sort controls.
 * Both are optional and travel together: a delegations table and a focused run
 * render the same rows with nothing to sort - the order came from the one query
 * that asked for them - so they pass neither and get plain headers. When they
 * are given, the sort is the server's over the whole narrowed set, never this
 * page of rows: the slowest run of a month is not in whichever twenty-five a
 * feed returned.
 */
export function RunTable({
  runs,
  sort,
  onSort,
  onOpen,
  agentsById,
  membersById,
}: {
  runs: AgentRun[];
  sort?: RunSort;
  onSort?: (sort: RunSort) => void;
  /** Opens a row's detail. Given, every row becomes clickable; a delegations
   * table and a focused run pass nothing - the detail is already on screen. */
  onOpen?: (run: AgentRun) => void;
  /** Names for the Agent column, keyed by id. Given only by a caller whose
   * reader holds agents:view - the column is withheld, not dashed out, when
   * the names cannot be resolved. */
  agentsById?: Map<string, { name: string; has_avatar?: boolean }>;
  /** Faces for the User column, from the member list any member may read. */
  membersById?: Map<string, IdentifiedMember>;
}) {
  const t = useTranslations("pages.runs");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const meId = useAuthStore((state) => state.user?.id ?? null);
  const sortable = sort !== undefined && onSort !== undefined;

  const columns: Column<AgentRun>[] = [
    {
      key: "status",
      header: t("status"),
      className: "pl-5",
      cell: (run) => (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <RunStatusBadge status={run.status} />
            {/* The reason this list is worth reading top to bottom: an
                answer somebody said was wrong. A marker, not a count -
                the row links to the detail where the comment is read. */}
            {run.down_rated && (
              <ThumbsDown
                role="img"
                aria-label={t("ratedDown")}
                className="text-destructive h-3.5 w-3.5 shrink-0"
              />
            )}
          </div>
          {run.parent_run_id !== null && (
            <Badge variant="outline" className="block w-fit" title={t("delegatedCostIsAlreadyIn")}>
              {/* The task id when there is one, because it is what makes
                  this row and a delegation panel in a transcript visibly
                  the same delegation rather than two things about the same
                  agent. It is withheld for an orphan, whose parent - and
                  whose transcript - has been deleted. */}
              {run.subagent_task_id === null
                ? t("delegated")
                : t("delegatedTask", { taskId: run.subagent_task_id })}
            </Badge>
          )}
        </div>
      ),
    },
    ...(agentsById !== undefined
      ? ([
          {
            key: "agent",
            header: t("agentColumn"),
            cell: (run) => {
              const agent = agentsById.get(run.agent_id);
              if (agent === undefined) {
                return <span className="text-muted-foreground text-xs">-</span>;
              }
              return (
                <span className="flex items-center gap-2 text-xs">
                  <span aria-hidden>
                    <AgentAvatar
                      agentId={run.agent_id}
                      name={agent.name}
                      hasAvatar={agent.has_avatar ?? false}
                      size="sm"
                      className="h-5 w-5"
                    />
                  </span>
                  {agent.name}
                </span>
              );
            },
          },
        ] as Column<AgentRun>[])
      : []),
    ...(membersById !== undefined
      ? ([
          {
            key: "user",
            header: t("personColumn"),
            cell: (run) => {
              const member = run.user_id === null ? undefined : membersById.get(run.user_id);
              if (member === undefined) {
                return <span className="text-muted-foreground text-xs">-</span>;
              }
              return (
                <span className="flex items-center gap-2 text-xs">
                  <EntityAvatar
                    seed={member.user_id}
                    name={member.full_name || member.email}
                    imageSrc={`/api/users/avatar/${member.user_id}`}
                    className="h-5 w-5 shrink-0 text-[9px]"
                    ariaHidden
                  />
                  {displayName(member)}
                </span>
              );
            },
          },
        ] as Column<AgentRun>[])
      : []),
    {
      key: "surface",
      header: t("surface"),
      // The mark and the name together: the mark is what makes a column of
      // fifty rows scannable, the name is what a screen reader hears.
      cell: (run) => (
        <span className="text-muted-foreground flex items-center gap-1.5">
          <SurfaceIcon surface={run.surface} />
          {surfaceLabel(run.surface, t)}
        </span>
      ),
    },
    {
      key: "model",
      header: t("model"),
      // The vendor's mark beside the profile label, the way the Builder's
      // current-model row draws it - one presentation for a model everywhere.
      cell: (run) => (
        <span className="flex items-center gap-1.5 font-mono text-xs">
          {run.provider !== null && (
            <ProviderIcon provider={run.provider} className="h-3.5 w-3.5" />
          )}
          {run.model_label ?? "-"}
        </span>
      ),
    },
    {
      key: "tokens",
      header: t("tokens"),
      align: "right",
      sortable,
      cell: (run) => (
        <span className="font-mono text-xs">{run.input_tokens + run.output_tokens}</span>
      ),
    },
    {
      key: "cost",
      header: t("cost"),
      align: "right",
      sortable,
      cell: (run) => (
        <span className="font-mono text-xs">
          ${Number(run.cost_usd).toFixed(4)}
          {run.cost_is_partial && (
            <span className="text-muted-foreground" title={t("modelRunHadNo")}>
              {" +"}
            </span>
          )}
        </span>
      ),
    },
    {
      key: "duration",
      header: t("took"),
      align: "right",
      sortable,
      // A still-running or parked run reads "-", the same absence the
      // duration sort places last in both directions - it has no
      // duration yet, which is a different fact from having been fast.
      cell: (run) => (
        <span className="text-muted-foreground font-mono text-xs">
          {formatRunDuration(run.started_at, run.ended_at)}
        </span>
      ),
    },
    {
      key: "started_at",
      header: t("started"),
      sortable,
      // Relative on the row, absolute on hover: a feed is scanned as "how long
      // ago", and the instant is one hover away when a reader needs to line a
      // run up against a deploy or a bill.
      cell: (run) =>
        run.started_at === null ? (
          <span className="text-muted-foreground text-xs">-</span>
        ) : (
          <span
            className="text-muted-foreground text-xs whitespace-nowrap"
            title={formatDateTime(run.started_at, locale)}
          >
            {timeAgo(run.started_at, tTime, locale)}
          </span>
        ),
    },
    {
      key: "conversation",
      header: "",
      align: "right",
      className: "pr-5",
      // The chat behind the run, one click away (#765) - only when there is a
      // conversation to open, and only on the reader's own runs: the chat page
      // lists its owner's threads, so anybody else's link would land on an
      // empty sidebar dressed as the conversation.
      cell: (run) =>
        run.conversation_id !== null && run.user_id !== null && run.user_id === meId ? (
          <Link
            href={`${ROUTES.CHAT}?id=${run.conversation_id}`}
            aria-label={t("openTheChatBehind")}
            title={t("openTheChatBehind")}
            className="text-muted-foreground hover:text-foreground inline-flex"
            // The link leaves the page; without this a clickable row would
            // also open the run detail underneath the navigation.
            onClick={(event) => event.stopPropagation()}
          >
            <MessageSquare className="h-4 w-4" aria-hidden />
          </Link>
        ) : null,
    },
  ];

  return (
    <DataTable<AgentRun>
      columns={columns}
      rows={runs}
      getRowKey={(run) => run.id}
      sort={sort}
      // The keys the two sortable columns carry are exactly `RunSortKey`, so the
      // widening to `string` on the way through the primitive is undone here.
      onSort={onSort ? (next) => onSort({ by: next.by as RunSortKey, dir: next.dir }) : undefined}
      onRowClick={onOpen}
      className="rounded-none border-0 bg-transparent [&_table]:min-w-[46rem]"
    />
  );
}
