"use client";

import { useState } from "react";
import Link from "next/link";
import { Bot, Database, Layers, LayoutTemplate, Plus, Star, Unlink, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ResourceIcon } from "@/components/ui/resource-icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { useProjectResources, useProjectResourceCandidates } from "@/hooks/use-project-resources";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FILL, DIALOG_BROAD } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/lib/constants";
import type {
  ProjectResource,
  ProjectResourceKind,
  ResourceCandidate,
} from "@/lib/project-resources-api";
import type { Project } from "@/types/projects";
import { Perm } from "@/types/permissions";

const kinds = ["agent", "workflow", "app", "table"] as const;
const icons = { agent: Bot, workflow: Workflow, app: LayoutTemplate, table: Database };
const permissions = {
  agent: Perm.agentsView,
  workflow: Perm.workflowsView,
  app: Perm.artifactsView,
  table: Perm.tablesView,
};
const href = (item: ProjectResource) =>
  ({
    agent: ROUTES.AGENT_DETAIL,
    workflow: ROUTES.WORKFLOW_DETAIL,
    app: ROUTES.ARTIFACT_DETAIL,
    table: ROUTES.TABLE_DETAIL,
  })[item.kind](item.resource_id);

export function ProjectResources({ project }: { project: Project }) {
  const t = useTranslations("projects.resources");
  const errors = useTranslations("errors");
  const [search, setSearch] = useState("");
  const [adding, setAdding] = useState(false);
  const resources = useProjectResources(project.id, search);
  const failure = resources.error ?? resources.remove.error ?? resources.entrypoint.error;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4" data-tour="project-resources">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t("search")}
          className="max-w-sm"
        />
        {project.can_edit && (
          <Button onClick={() => setAdding(true)}>
            <Plus aria-hidden className="size-4" />
            {t("add")}
          </Button>
        )}
      </div>
      <p className="text-muted-foreground text-sm">{t("hint")}</p>
      {failure && <ErrorState description={getErrorMessage(failure, errors)} />}
      {resources.isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : resources.data?.items.length === 0 ? (
        <EmptyState className="flex-1" icon={Layers} title={t("empty")} />
      ) : (
        <ul className="divide-border min-h-0 flex-1 divide-y overflow-y-auto rounded-xl border">
          {resources.data?.items.map((item) => {
            return (
              <li
                key={`${item.kind}:${item.resource_id}`}
                className="flex flex-wrap items-center gap-3 p-3"
              >
                <ResourceMark kind={item.kind} item={{ id: item.resource_id, ...item }} />
                <div className="min-w-0 flex-1">
                  <Link href={href(item)} className="hover:underline">
                    {item.name}
                  </Link>
                  <p className="text-muted-foreground text-sm">
                    {t(item.kind)}
                    {item.is_entrypoint && ` · ${t("main")}`}
                  </p>
                  {item.description && (
                    <p className="text-muted-foreground mt-1 line-clamp-2 text-sm">
                      {item.description}
                    </p>
                  )}
                </div>
                {project.can_edit && (
                  <div className="flex gap-1">
                    {item.kind === "workflow" && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={item.is_entrypoint ? t("unsetMain") : t("setMain")}
                        title={item.is_entrypoint ? t("unsetMain") : t("setMain")}
                        disabled={resources.entrypoint.isPending}
                        onClick={() =>
                          resources.entrypoint.mutate(item.is_entrypoint ? null : item.resource_id)
                        }
                      >
                        <Star aria-hidden className={item.is_entrypoint ? "fill-current" : ""} />
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("remove", { name: item.name })}
                      title={t("remove", { name: item.name })}
                      disabled={resources.remove.isPending}
                      onClick={() => resources.remove.mutate(item)}
                    >
                      <Unlink aria-hidden />
                    </Button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {adding && <AddResources projectId={project.id} close={() => setAdding(false)} />}
    </div>
  );
}

function AddResources({ projectId, close }: { projectId: string; close: () => void }) {
  const t = useTranslations("projects.resources");
  const common = useTranslations("common");
  const errors = useTranslations("errors");
  const { can } = usePermissions();
  const allowed = kinds.filter((kind) => can(permissions[kind]));
  const [chosenKind, setKind] = useState<ProjectResourceKind | null>(null);
  const kind = allowed.find((item) => item === chosenKind) ?? allowed[0] ?? "agent";
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const candidates = useProjectResourceCandidates(kind, allowed.includes(kind));
  const resources = useProjectResources(projectId);
  const linked = new Set(
    resources.data?.items.filter((item) => item.kind === kind).map((item) => item.resource_id),
  );
  const failure = resources.add.error ?? candidates.error;
  const filtered = (candidates.data ?? []).filter((item) =>
    `${item.name} ${item.description ?? ""}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !resources.add.isPending) close();
      }}
    >
      <DialogContent
        dismissible={!resources.add.isPending}
        className={cn(DIALOG_BROAD, DIALOG_FILL)}
      >
        <DialogHeader>
          <DialogTitle>{t("add")}</DialogTitle>
          <DialogDescription>{t("hint")}</DialogDescription>
        </DialogHeader>
        <Select
          value={kind}
          onValueChange={(value) => {
            const next = kinds.find((item) => item === value);
            if (next) {
              setKind(next);
              setSelected([]);
            }
          }}
        >
          <SelectTrigger aria-label={t("kind")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {allowed.map((item) => (
              <SelectItem key={item} value={item}>
                <span className="inline-flex items-center gap-2">
                  <ResourceMark kind={item} compact />
                  {t(item)}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={t("search")}
          className="shrink-0"
        />
        {failure && <ErrorState description={getErrorMessage(failure, errors)} />}
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto" aria-busy={candidates.isLoading}>
          {!candidates.isLoading && !failure && filtered.length === 0 && (
            <p className="text-muted-foreground py-8 text-center text-sm">{t("noMatches")}</p>
          )}
          {candidates.isLoading ? (
            <LoadingState variant="skeleton-list" rows={3} />
          ) : (
            filtered.map((item) => (
              <label
                key={item.id}
                className="hover:bg-muted flex min-h-16 cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5"
              >
                <Checkbox
                  aria-label={item.name}
                  checked={linked.has(item.id) || selected.includes(item.id)}
                  disabled={
                    linked.has(item.id) ||
                    resources.add.isPending ||
                    (!selected.includes(item.id) && selected.length >= 100)
                  }
                  onCheckedChange={(checked) =>
                    setSelected((ids) =>
                      checked === true ? [...ids, item.id] : ids.filter((id) => id !== item.id),
                    )
                  }
                />
                <ResourceMark kind={kind} item={item} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{item.name}</span>
                  <span className="text-muted-foreground mt-0.5 line-clamp-2 block text-xs">
                    {item.description || t(kind)}
                  </span>
                </span>
              </label>
            ))
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={close} disabled={resources.add.isPending}>
            {common("cancel")}
          </Button>
          <Button
            disabled={!selected.length || resources.add.isPending}
            onClick={() =>
              resources.add.mutate(
                selected.map((resource_id) => ({ kind, resource_id })),
                { onSuccess: close },
              )
            }
          >
            {t("addSelected", { count: selected.length })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResourceMark({
  kind,
  item,
  compact = false,
}: {
  kind: ProjectResourceKind;
  item?: ResourceCandidate;
  compact?: boolean;
}) {
  if (kind === "agent" && item?.slug)
    return (
      <AgentAvatar
        agentId={item.id}
        slug={item.slug}
        hasAvatar={item.has_avatar}
        colorSlot={item.avatar_color}
        size="md"
      />
    );
  if (kind === "workflow" || kind === "table")
    return (
      <ResourceIcon
        kind={kind}
        className={compact ? "size-6 [&_svg]:size-3.5" : "size-9 [&_svg]:size-4"}
      />
    );
  const Icon = icons[kind];
  return (
    <span
      className={cn(
        "bg-muted text-muted-foreground grid shrink-0 place-items-center rounded-xl",
        compact ? "size-6" : "size-9",
      )}
      aria-hidden
    >
      <Icon className={compact ? "size-3.5" : "size-4"} />
    </span>
  );
}
