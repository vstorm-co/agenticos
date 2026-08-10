"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Bot, Plus, Search } from "lucide-react";

import { AgentCard } from "@/components/agents/agent-card";
import { CreateAgentDialog } from "@/components/agents/create-agent-dialog";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
} from "@/components/ui";
import { useAgents, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { Agent, AgentStatus } from "@/types/agents";
import { useTranslations } from "next-intl";

type Filter = "all" | AgentStatus;

const FILTERS: { label: string; value: Filter }[] = [
  { label: "All", value: "all" },
  { label: "Published", value: "published" },
  { label: "Drafts", value: "draft" },
  { label: "Archived", value: "archived" },
];

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
  const t = useTranslations("pages.agents");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("catalog")}</CardTitle>
          <CardDescription className="text-xs">
            {visible === null ? (
              <Skeleton className="h-3 w-24" />
            ) : visible === total ? (
              t("shownCount", { count: total })
            ) : (
              /* Honest about a filter narrowing the view. */
              t("shownOfTotal", { visible, total })
            )}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-5">{children}</CardContent>
    </Card>
  );
}

export default function AgentsPage() {
  const t = useTranslations("pages.agents");
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
        title={t("agents")}
        description={t("agentConfigurationNotCode")}
        actions={
          canEdit ? (
            <Button data-tour="agents-new" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("newAgent")}
            </Button>
          ) : undefined
        }
      />

      {/* Both controls narrow the same list, so they sit together on the right
          rather than at opposite ends of the row. As a segmented control the
          four statuses took the width of a heading on the left, which read as a
          section title for the page rather than as a filter on the gallery. */}
      <div data-tour="agents-filters" className="flex flex-wrap items-center justify-end gap-2">
        <Select value={filter} onValueChange={(value) => setFilter(value as Filter)}>
          <SelectTrigger className="w-full sm:w-40" aria-label={t("filterByStatus")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FILTERS.map((entry) => (
              <SelectItem key={entry.value} value={entry.value}>
                {entry.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="relative w-full sm:w-64">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("searchAgents")}
            aria-label={t("searchAgents2")}
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
                {agents.length === 0 ? t("noAgentsYet") : t("nothingMatches")}
              </p>
              <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
                {agents.length === 0
                  ? canEdit
                    ? t("createOneGiveInstructions")
                    : t("nobodyHasSharedAgent")
                  : t("noAgentHereMatches")}
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
                  {t("clearFilters")}
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
          description={t("stopsAnsweringEverywhereAvailable2")}
          confirmLabel={t("archive2")}
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
          description={t("removesAgentEveryVersion2")}
          confirmLabel={t("delete2")}
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
