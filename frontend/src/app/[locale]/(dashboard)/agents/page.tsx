"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Plus, Search } from "lucide-react";

import { AgentCard } from "@/components/agents/agent-card";
import { CreateAgentDialog } from "@/components/agents/create-agent-dialog";
import { PageHeader } from "@/components/dashboard/page-header";
import { SegmentedControl } from "@/components/dashboard/segmented-control";
import { EmptyState, LoadingState } from "@/components/states";
import { Button, ConfirmDialog, Input } from "@/components/ui";
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
          list loads rather than being replaced by a placeholder of themselves. */}
      {isLoading ? (
        <LoadingState variant="skeleton-cards" />
      ) : visible.length === 0 ? (
        <EmptyState
          icon={Bot}
          title={agents.length === 0 ? "No agents yet" : "Nothing matches"}
          description={
            agents.length === 0
              ? canEdit
                ? "Create one, give it instructions and a few capabilities, then publish it."
                : "Nobody has shared an agent with you yet."
              : "No agent here matches that filter and search."
          }
          cta={
            agents.length > 0
              ? {
                  label: "Clear filters",
                  onClick: () => {
                    setFilter("all");
                    setQuery("");
                  },
                }
              : undefined
          }
        />
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
