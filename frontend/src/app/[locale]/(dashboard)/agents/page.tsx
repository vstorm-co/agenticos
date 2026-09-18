"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Bot, Library, Plus } from "lucide-react";

import { AgentCard } from "@/components/agents/agent-card";
import { AgentTemplateDialog } from "@/components/agents/agent-template-dialog";
import { ChipsInput } from "@/components/agents/chips-input";
import { CreateAgentDialog } from "@/components/agents/create-agent-dialog";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  ConfirmDialog,
  ListCard,
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  SearchInput,
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

/** The shared list-card, with this page's count line - honest about a filter
 * narrowing the view. */
function AgentsCard({
  visible,
  total,
  controls,
  children,
}: {
  visible: number | null;
  total: number;
  controls?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("pages.agents");
  return (
    <ListCard
      title={t("catalog")}
      counted={
        visible === null
          ? null
          : visible === total
            ? t("shownCount", { count: total })
            : t("shownOfTotal", { visible, total })
      }
      controls={controls}
    >
      {children}
    </ListCard>
  );
}

export default function AgentsPage() {
  const t = useTranslations("pages.agents");
  const tc = useTranslations("common");
  const router = useRouter();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  // The discovery facet is server-driven: it filters the whole set rather than
  // the fetched page, so it drives the request rather than the client `useMemo`
  // the status and text filters do.
  const [categories, setCategories] = useState<string[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const tTemplates = useTranslations("agentTemplates");
  const [pendingDelete, setPendingDelete] = useState<Agent | null>(null);
  const [pendingArchive, setPendingArchive] = useState<Agent | null>(null);

  // Archived agents are fetched only when they could be shown. The list is the
  // same query otherwise, so switching between the first three filters costs
  // nothing.
  const { agents, total, isLoading, clone, archive, unarchive, remove } = useAgents({
    includeArchived: filter === "all" || filter === "archived",
    categories,
    tags,
  });
  const { can } = usePermissions();
  const canEdit = can(Perm.agentsEdit);

  // Any narrowing at all - the client status/text filters and the server facet.
  // A zero-match facet returns an empty page, so this is what tells "no agent
  // matched" from "no agents exist", and it gates the Clear-filters CTA.
  const filtersActive =
    filter !== "all" || query.trim() !== "" || categories.length > 0 || tags.length > 0;

  const clearFilters = () => {
    setFilter("all");
    setQuery("");
    setCategories([]);
    setTags([]);
  };

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

  // Both controls narrow the gallery, so they live in its card header - the
  // container's own controls slot, like every list card's.
  const galleryControls = (
    <div data-tour="agents-filters" className="flex flex-wrap items-center gap-2">
      <Select value={filter} onValueChange={(value) => setFilter(value as Filter)}>
        <SelectTrigger className="w-40" aria-label={t("filterByStatus")}>
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
      <SearchInput value={query} onChange={setQuery} placeholder={t("searchAgents2")} />
      <ChipsInput
        values={categories}
        onChange={setCategories}
        inputLabel={t("filterByCategory")}
        removeLabel={(value) => t("removeCategoryFilter", { value })}
        placeholder={t("filterByCategory")}
        maxItems={10}
        maxLength={32}
      />
      <ChipsInput
        values={tags}
        onChange={setTags}
        inputLabel={t("filterByTag")}
        removeLabel={(value) => t("removeTagFilter", { value })}
        placeholder={t("filterByTag")}
        maxItems={20}
        maxLength={32}
      />
    </div>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("agents")}
        description={t("agentConfigurationNotCode")}
        actions={
          canEdit ? (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                data-tour="agents-templates"
                onClick={() => setTemplatesOpen(true)}
              >
                <Library className="h-4 w-4" />
                {tTemplates("browse")}
              </Button>
              <Button data-tour="agents-new" onClick={() => setCreateOpen(true)}>
                <Plus className="h-4 w-4" />
                {t("newAgent")}
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* The header and the controls are static, so they stay put while the
          list loads rather than being replaced by a placeholder of themselves.
          The panel below is equally static - loading, empty and populated all
          render inside the same frame. */}
      {isLoading ? (
        <AgentsCard visible={null} total={0} controls={galleryControls}>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
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
        <AgentsCard visible={visible.length} total={total} controls={galleryControls}>
          {visible.length === 0 ? (
            <ListCardEmpty
              icon={Bot}
              title={filtersActive ? t("nothingMatches") : t("noAgentsYet")}
              description={
                filtersActive
                  ? t("noAgentHereMatches")
                  : canEdit
                    ? t("createOneGiveInstructions")
                    : t("nobodyHasSharedAgent")
              }
              cta={
                filtersActive
                  ? {
                      label: t("clearFilters"),
                      onClick: clearFilters,
                    }
                  : undefined
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
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

      <AgentTemplateDialog open={templatesOpen} onOpenChange={setTemplatesOpen} />
      <CreateAgentDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(agent) => router.push(ROUTES.AGENT_DETAIL(agent.id))}
      />

      {pendingArchive && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingArchive(null)}
          title={tc("archiveNamedConfirm", { name: pendingArchive.name })}
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
          title={tc("deleteNamedConfirm", { name: pendingDelete.name })}
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
