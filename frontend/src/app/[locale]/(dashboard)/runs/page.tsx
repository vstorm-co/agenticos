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

export default function RunsPage() {
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
        <PageHeader
          title="Activity"
          description="What your agents did, what it cost, and what is waiting on a person."
        />
        {/* The three figures and the run table, in that order - the tabs are
            omitted rather than faked, because a tab strip with no tab to select
            invites a click that does nothing. */}
        <LoadingState variant="stats" rows={3} className="gap-3 sm:grid-cols-3 lg:grid-cols-3" />
        <Card>
          <CardHeader>
            <CardTitle>Run history</CardTitle>
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
      <PageHeader
        title="Activity"
        description="What your agents did, what it cost, and what is waiting on a person."
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              Spend this month
            </p>
            <p className="font-mono text-2xl">
              ${Number(spend?.month_to_date_usd ?? 0).toFixed(2)}
            </p>
            <p className="text-muted-foreground text-xs">
              Calendar month, so it reconciles against an invoice.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">Runs</p>
            <p className="font-mono text-2xl">{runs.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-1 p-5">
            <p className="text-muted-foreground text-xs tracking-wide uppercase">
              Waiting on a person
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
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="spend">Spend</TabsTrigger>
        </TabsList>

        <TabsContent value="approvals">
          <Card>
            <CardHeader>
              <CardTitle>Waiting for a decision</CardTitle>
              <CardDescription>
                The arguments are shown in full. Approving a tool name without seeing what it will
                do is a rubber stamp, not approval.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {approvals.length === 0 ? (
                <EmptyState
                  icon={CheckCircle2}
                  title="Nothing waiting"
                  description="Agents are running without needing you."
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
                          Approve
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => decide.mutate({ id: approval.id, approved: false })}
                        >
                          <XCircle className="h-4 w-4" />
                          Reject
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
              <CardTitle>Run history</CardTitle>
              <CardDescription>
                Every run records the agent <em>version</em> it executed, so what happened last week
                stays answerable after the agent has been rewritten.
              </CardDescription>
              {/* Said out loud, with the way out beside it. A filtered table that
                  does not mention the filter is a table somebody reads as the
                  whole history, and then wonders where the rest of the runs went. */}
              {agentId !== null && (
                <p className="text-muted-foreground text-xs">
                  Narrowed to one agent.{" "}
                  <Link href={ROUTES.RUNS} className="underline underline-offset-4">
                    Show every agent
                  </Link>
                </p>
              )}
            </CardHeader>
            <CardContent>
              {runs.length === 0 ? (
                <EmptyState icon={Activity} title="No runs yet" description="Nothing has run." />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[40rem] text-sm">
                    <thead>
                      <tr className="text-muted-foreground border-b text-left">
                        <th className="py-2 font-medium">Status</th>
                        <th className="px-3 py-2 font-medium">Surface</th>
                        <th className="px-3 py-2 font-medium">Model</th>
                        <th className="px-3 py-2 text-right font-medium">Tokens</th>
                        <th className="px-3 py-2 text-right font-medium">Cost</th>
                        <th className="px-3 py-2 font-medium">Started</th>
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
                              <span
                                className="text-muted-foreground"
                                title="A model in this run had no price, so this is a floor"
                              >
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
              title="By provider"
              description="What each vendor was paid - this is the number an invoice is checked against."
              rows={(spend?.by_provider ?? []).map((entry) => ({
                key: entry.provider ?? "unrecorded",
                label: entry.provider ?? "Not recorded",
                muted: entry.provider === null,
                runs: entry.run_count,
                cost: entry.cost_usd,
              }))}
            />
            <SpendBreakdown
              title="By key"
              description="Which stored credential it was spent through. A key you do not recognise here is one to rotate."
              rows={(spend?.by_key ?? []).map((entry) => ({
                key: entry.secret_id ?? "deleted",
                label: entry.label ?? "Deleted key",
                muted: entry.label === null,
                runs: entry.run_count,
                cost: entry.cost_usd,
              }))}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Spend by agent</CardTitle>
              <CardDescription>Last {spend?.period_days ?? 30} days.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {!spend || spend.by_agent.length === 0 ? (
                <p className="text-muted-foreground text-sm">Nothing spent yet.</p>
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
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {rows.length === 0 ? (
          <p className="text-muted-foreground text-sm">Nothing spent yet.</p>
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
