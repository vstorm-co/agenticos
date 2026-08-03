"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Activity, CheckCircle2, XCircle } from "lucide-react";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useApprovals, usePermissions, useRuns, useSpend } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

export default function RunsPage() {
  const t = useTranslations("pages.runs");
  // `?agent=` is how the Builder hands over. Its Recent runs panel answers the
  // summary question and links here for the detail, and arriving at the whole
  // organization's history after clicking through from one agent would make the
  // link a dead end dressed as a filter.
  const searchParams = useSearchParams();
  const agentId = searchParams.get("agent");
  const { runs, isLoading } = useRuns(agentId ?? undefined);
  const { approvals, decide } = useApprovals();
  const { spend } = useSpend(30);
  const { can } = usePermissions();

  const canDecide = can(Perm.approvalsDecide);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("activity")} description={t("whatYourAgentsDid")} />
        {/* The three figures and the run table, in that order - the tabs are
            omitted rather than faked, because a tab strip with no tab to select
            invites a click that does nothing. */}
        <LoadingState variant="stats" rows={3} className="gap-3 sm:grid-cols-3 lg:grid-cols-3" />
        <Card>
          <CardHeader>
            <CardTitle>{t("runHistory")}</CardTitle>
          </CardHeader>
          <CardContent>
            <LoadingState variant="skeleton-table" columns={6} rows={6} />
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader title={t("activity2")} description={t("whatYourAgentsDid2")} />

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              {t("spendMonth")}
            </p>
            <p className="font-mono text-2xl">
              ${Number(spend?.month_to_date_usd ?? 0).toFixed(2)}
            </p>
            <p className="text-muted-foreground text-xs">{t("calendarMonthSoReconciles")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">{t("runs")}</p>
            <p className="font-mono text-2xl">{runs.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              {t("waitingPerson")}
            </p>
            <p className="font-mono text-2xl">{approvals.length}</p>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="approvals">
        <TabsList>
          <TabsTrigger value="approvals">
            Approvals
            {approvals.length > 0 && (
              <Badge variant="secondary" className="ml-2">
                {approvals.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="runs">{t("runs2")}</TabsTrigger>
          <TabsTrigger value="spend">{t("spend")}</TabsTrigger>
        </TabsList>

        <TabsContent value="approvals">
          <Card>
            <CardHeader>
              <CardTitle>{t("waitingDecision")}</CardTitle>
              <CardDescription>{t("argumentsAreShownFull")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {approvals.length === 0 ? (
                <EmptyState
                  icon={CheckCircle2}
                  title={t("nothingWaiting")}
                  description={t("agentsAreRunningWithout")}
                />
              ) : (
                approvals.map((approval) => (
                  <div key={approval.id} className="space-y-3 rounded-md border p-4">
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-mono text-sm">{approval.tool_id}</span>
                      <span className="text-muted-foreground text-xs">
                        {approval.created_at ? formatDate(approval.created_at) : ""}
                      </span>
                    </div>
                    <pre className="bg-muted/40 overflow-x-auto rounded p-3 text-xs">
                      {JSON.stringify(approval.tool_args, null, 2)}
                    </pre>
                    {canDecide && (
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => decide.mutate({ id: approval.id, approved: true })}
                        >
                          <CheckCircle2 className="h-4 w-4" />
                          {t("approve")}
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => decide.mutate({ id: approval.id, approved: false })}
                        >
                          <XCircle className="h-4 w-4" />
                          {t("reject")}
                        </Button>
                      </div>
                    )}
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="runs">
          <Card>
            <CardHeader>
              <CardTitle>{t("runHistory2")}</CardTitle>
              <CardDescription>
                Every run records the agent <em>{t("version")}</em>
                {t("executedSoWhatHappened")}
              </CardDescription>
              {/* Said out loud, with the way out beside it. A filtered table that
                  does not mention the filter is a table somebody reads as the
                  whole history, and then wonders where the rest of the runs went. */}
              {agentId !== null && (
                <p className="text-muted-foreground text-xs">
                  Narrowed to one agent.{" "}
                  <Link href={ROUTES.RUNS} className="underline underline-offset-4">
                    {t("showEveryAgent")}
                  </Link>
                </p>
              )}
            </CardHeader>
            <CardContent>
              {runs.length === 0 ? (
                <EmptyState
                  icon={Activity}
                  title={t("noRunsYet")}
                  description={t("nothingHasRun")}
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-sm">
                    <thead>
                      <tr className="text-muted-foreground border-b text-left">
                        <th className="py-2 font-medium">{t("status")}</th>
                        <th className="px-3 py-2 font-medium">{t("surface")}</th>
                        <th className="px-3 py-2 font-medium">{t("model")}</th>
                        <th className="px-3 py-2 text-right font-medium">{t("tokens")}</th>
                        <th className="px-3 py-2 text-right font-medium">{t("cost")}</th>
                        <th className="px-3 py-2 font-medium">{t("started")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((run) => (
                        <tr key={run.id} className="border-b last:border-0">
                          <td className="py-2">
                            <RunStatusBadge status={run.status} />
                          </td>
                          <td className="text-muted-foreground px-3 py-2">{run.surface}</td>
                          <td className="px-3 py-2 font-mono text-xs">{run.model_label ?? "-"}</td>
                          <td className="px-3 py-2 text-right font-mono text-xs">
                            {run.input_tokens + run.output_tokens}
                          </td>
                          <td className="px-3 py-2 text-right font-mono text-xs">
                            ${Number(run.cost_usd).toFixed(4)}
                            {run.cost_is_partial && (
                              <span className="text-muted-foreground" title={t("modelRunHadNo")}>
                                {" +"}
                              </span>
                            )}
                          </td>
                          <td className="text-muted-foreground px-3 py-2 text-xs">
                            {run.started_at ? formatDate(run.started_at) : "-"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="spend" className="space-y-4">
          {/* Three answers to "where did the money go", because they are three
              different questions: which agent is expensive, which vendor is
              being paid, and which key is being spent through. Only the first
              existed, and it is the one that cannot be checked against a bill. */}
          <div className="grid gap-4 md:grid-cols-2">
            <SpendBreakdown
              title={t("byProvider")}
              description={t("whatEachVendorWas")}
              rows={(spend?.by_provider ?? []).map((entry) => ({
                key: entry.provider ?? "unrecorded",
                label: entry.provider ?? t("notRecorded"),
                muted: entry.provider === null,
                runs: entry.run_count,
                cost: entry.cost_usd,
              }))}
            />
            <SpendBreakdown
              title={t("byKey")}
              description={t("whichStoredCredentialWas")}
              rows={(spend?.by_key ?? []).map((entry) => ({
                key: entry.secret_id ?? "deleted",
                label: entry.label ?? t("deletedKey"),
                muted: entry.label === null,
                runs: entry.run_count,
                cost: entry.cost_usd,
              }))}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>{t("spendByAgent")}</CardTitle>
              <CardDescription>Last {spend?.period_days ?? 30} days.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {!spend || spend.by_agent.length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("nothingSpentYet")}</p>
              ) : (
                spend.by_agent.map((entry) => (
                  <div
                    key={`${entry.agent_id}-${entry.model_label}`}
                    className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
                  >
                    <span className="font-mono text-xs">{entry.model_label ?? "-"}</span>
                    <span className="text-muted-foreground text-xs">{entry.run_count} runs</span>
                    <span className="font-mono">${Number(entry.cost_usd).toFixed(4)}</span>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

/**
 * One way of slicing the same spend.
 *
 * A row whose subject no longer exists - a provider from before this was
 * recorded, a key since deleted - is kept and muted rather than dropped. The
 * money was spent either way, and a breakdown that silently stops adding up to
 * the total is worse than one with an honest "not recorded" line in it.
 */
function SpendBreakdown({
  title,
  description,
  rows,
}: {
  title: string;
  description: string;
  rows: { key: string; label: string; muted: boolean; runs: number; cost: string }[];
}) {
  const t = useTranslations("pages.runs");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("nothingSpentYet2")}</p>
        ) : (
          rows.map((row) => (
            <div
              key={row.key}
              className="flex items-center justify-between gap-3 rounded-md border p-3 text-sm"
            >
              <span className={row.muted ? "text-muted-foreground italic" : "font-medium"}>
                {row.label}
              </span>
              <span className="text-muted-foreground ml-auto text-xs">{row.runs} runs</span>
              <span className="font-mono">${Number(row.cost).toFixed(4)}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
