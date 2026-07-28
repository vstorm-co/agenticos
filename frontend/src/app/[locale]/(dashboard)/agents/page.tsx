"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Bot, Plus, Search } from "lucide-react";

import { AgentCard } from "@/components/agents/agent-card";
import { CreateAgentDialog } from "@/components/agents/create-agent-dialog";
import { PageHeader } from "@/components/dashboard/page-header";
import { SegmentedControl } from "@/components/dashboard/segmented-control";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Input,
  Skeleton,
} from "@/components/ui";
import { useAgents, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { Agent, AgentStatus } from "@/types/agents";

type Filter = "all" | AgentStatus;

const FILTERS: { label: string; value: Filter }[] = [
  { label: "All", value: "all" },
  { label: "Published", value: "published" },
  { label: "Drafts", value: "draft" },
  { label: "Archived", value: "archived" },
];

/** The gallery count, in words, honest about a filter narrowing the view. */
function shownCount(visible: number, total: number): string {
  if (visible === total) return total === 1 ? "1 agent" : `${total} agents`;
  return `${visible} of ${total} shown`;
}

/**
 * The gallery's frame, drawn whether or not anything is in it - the same
 * bargain as the vault's KeysCard: one panel with one header in every state,
 * so an emptied filter changes what is inside the panel, never the page shape.
 */
function AgentsCard({
  visible,
  total,
  children,
}: {
  visible: number | null;
  total: number;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">Catalog</CardTitle>
          <CardDescription className="text-xs">
            {visible === null ? (
              <Skeleton className="h-3 w-24" />
            ) : (
              shownCount(visible, total)
            )}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-5">{children}</CardContent>
    </Card>
  );
}

export default function AgentsPage() {
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);
  const [pendingArchive, setPendingArchive] = useState<Agent | null>(null);

  // Archived agents are fetched only when they could be shown. The list is the
  // same query otherwise, so switching between the first three filters costs
  // nothing.
  const { agents, isLoading, clone, archive, unarchive, remove } = useAgents({
    includeArchived: filter === "all" || filter === "archived",
  });
  const { can } = usePermissions();
  const canEdit = can(Perm.agentsEdit);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return agents
      .filter((agent) => filter === "all" || agent.status === filter)
      .filter(
        (agent) =>
          !needle ||
          agent.name.toLowerCase().includes(needle) ||
          agent.slug.toLowerCase().includes(needle) ||
          (agent.description ?? "").toLowerCase().includes(needle),
      );
  }, [agents, filter, query]);

  const busyId =
    clone.isPending || archive.isPending || unarchive.isPending || remove.isPending
      ? (clone.variables ?? archive.variables ?? unarchive.variables ?? remove.variables)
      : undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Agents"
        description="An agent is configuration, not code. Build it here, publish a version, and it runs the same way everywhere - chat, API, Slack."
        actions={
          canEdit ? (
            <Button onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              New agent
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          value={filter}
          onChange={(value) => setFilter(value as Filter)}
          options={FILTERS.map((entry) => ({ label: entry.label, value: entry.value }))}
        />
        <div className="relative w-full sm:w-64">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search agents…"
            aria-label="Search agents"
            className="pl-9"
          />
        </div>
      </div>

      {/* The header and the controls are static, so they stay put while the
          list loads rather than being replaced by a placeholder of themselves.
          The panel below is equally static - loading, empty and populated all
          render inside the same frame. */}
      {isLoading ? (
        <AgentsCard visible={null} total={0}>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((row) => (
              <div key={row} className="border-border rounded-xl border p-4">
                <div className="flex items-start gap-3">
                  <Skeleton className="h-10 w-10 shrink-0 rounded-lg" />
                  <div className="min-w-0 flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-24" />
                    <Skeleton className="h-3 w-full" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </AgentsCard>
      ) : (
        <AgentsCard visible={visible.length} total={agents.length}>
          {visible.length === 0 ? (
            <div className="px-6 py-16 text-center">
              <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
                <Bot className="h-5 w-5" />
              </div>
              <p className="text-foreground mt-4 text-sm font-medium">
                {agents.length === 0 ? "No agents yet" : "Nothing matches"}
              </p>
              <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
                {agents.length === 0
                  ? canEdit
                    ? "Create one, give it instructions and a few capabilities, then publish it."
                    : "Nobody has shared an agent with you yet."
                  : "No agent here matches that filter and search."}
              </p>
              {agents.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-5"
                  onClick={() => {
                    setFilter("all");
                    setQuery("");
                  }}
                >
                  Clear filters
                </Button>
              )}
            </div>
          ) : (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {visible.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  canEdit={canEdit}
                  busy={busyId === agent.id}
                  actions={{
                    onDuplicate: () =>
                      clone.mutate(agent.id, {
                        onSuccess: (created) => router.push(ROUTES.AGENT_DETAIL(created.id)),
                      }),
                    onArchive: () => setPendingArchive(agent),
                    onRestore: () => unarchive.mutate(agent.id),
                    onDelete: () => setPendingDelete(agent),
                  }}
                />
              ))}
            </div>
          )}
        </AgentsCard>
      )}

      <CreateAgentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(agent) => router.push(ROUTES.AGENT_DETAIL(agent.id))}
      />

      {pendingArchive && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingArchive(null)}
          title={`Archive ${pendingArchive.name}?`}
          description="It stops answering everywhere it is available. Its versions, runs and history are kept, and it can be restored."
          confirmLabel="Archive"
          loading={archive.isPending}
          onConfirm={async () => {
            await archive.mutateAsync(pendingArchive.id);
            setPendingArchive(null);
          }}
        />
      )}

      {pendingDelete && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={`Delete ${pendingDelete.name}?`}
          description="This removes the agent, every version of it and every share pointing at it. Its past runs are kept for the record. Archive instead if you only want it to stop."
          confirmLabel="Delete"
          confirmText={pendingDelete.slug}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </div>
  );
}
