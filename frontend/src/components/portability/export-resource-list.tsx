"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Bot,
  BookOpen,
  Database,
  FileText,
  Layers,
  Link2,
  Plug,
  Puzzle,
  Workflow,
} from "lucide-react";
import { Checkbox, Label, SearchInput } from "@/components/ui";
import { AgentAvatar, type AgentAvatarProps } from "@/components/agents/agent-avatar";
import { ProviderIcon } from "@/components/vault/provider-icon";
import type { BundlePreview, BundleResource } from "@/lib/portability-api";
import { ExportLayers } from "./export-layers";

const GROUPS = [
  "root",
  "agents",
  "workflows",
  "skills",
  "context",
  "knowledge",
  "connections",
  "other",
] as const;
type Group = (typeof GROUPS)[number];
function groupOf(item: BundleResource, root: boolean): Group {
  if (root) return "root";
  if (["agent", "agent_version"].includes(item.kind)) return "agents";
  if (item.kind === "workflow") return "workflows";
  if (["skill", "skill_fork", "skill_version"].includes(item.kind)) return "skills";
  if (item.kind === "context") return "context";
  if (item.kind === "knowledge_base") return "knowledge";
  if (
    [
      "model_profile",
      "mcp_connection",
      "embedding_endpoint",
      "sandbox_connection",
      "local_service",
      "secret",
    ].includes(item.kind)
  )
    return "connections";
  return "other";
}
function ResourceMark({ item, identity }: { item: BundleResource; identity?: AgentAvatarProps }) {
  const provider = item.definition?.provider;
  if (identity) return <AgentAvatar {...identity} size="md" />;
  const group = groupOf(item, false);
  const Icon = {
    agents: Bot,
    workflows: Workflow,
    skills: Puzzle,
    context: FileText,
    knowledge: BookOpen,
    connections: Plug,
    other: Database,
    root: Layers,
  }[group];
  return (
    <span
      className="bg-muted text-muted-foreground grid size-9 shrink-0 place-items-center rounded-xl"
      aria-hidden
    >
      {typeof provider === "string" ? (
        <ProviderIcon provider={provider} />
      ) : (
        <Icon className="size-4" />
      )}
    </span>
  );
}

export function ExportResourceList({
  data,
  format,
  busy,
  excluded,
  layersByKey,
  rootIdentity,
  onInclude,
  onLayers,
}: {
  data: BundlePreview;
  format: "yaml" | "json" | "zip";
  busy: boolean;
  excluded: ReadonlySet<string>;
  layersByKey: Readonly<Record<string, string[]>>;
  rootIdentity?: AgentAvatarProps;
  onInclude: (key: string, included: boolean) => void;
  onLayers: (key: string, selected: string[]) => void;
}) {
  const t = useTranslations("portability");
  const id = useId();
  const [search, setSearch] = useState("");
  const query = search.trim().toLocaleLowerCase();
  const visible = data.bundle.resources.filter((item) =>
    `${item.name} ${typeof item.definition?.description === "string" ? item.definition.description : ""}`
      .toLocaleLowerCase()
      .includes(query),
  );
  return (
    <fieldset className="min-w-0 space-y-3">
      <legend className="mb-2 text-sm font-medium">{t("includedContent")}</legend>
      {data.bundle.resources.length > 6 && (
        <SearchInput value={search} onChange={setSearch} placeholder={t("searchResources")} />
      )}
      {visible.length === 0 && (
        <p className="text-muted-foreground py-4 text-sm">{t("noResources")}</p>
      )}
      {GROUPS.map((group) => {
        const resources = visible.filter(
          (item) => groupOf(item, data.bundle.roots.includes(item.key)) === group,
        );
        if (!resources.length) return null;
        return (
          <section key={group} className="space-y-2" aria-label={t(`groups.${group}`)}>
            <h3 className="text-muted-foreground text-xs font-medium">{t(`groups.${group}`)}</h3>
            <div className="divide-border divide-y rounded-xl border">
              {resources.map((item) => {
                const root = data.bundle.roots.includes(item.key);
                const layers =
                  data.options.find((option) => option.key === item.key)?.layers ?? item.included;
                const included = layers.length > 0;
                const description = item.definition?.description;
                const model = item.definition?.model;
                const rowId = `${id}-${data.bundle.resources.indexOf(item)}`;
                return (
                  <div key={item.key} className="min-w-0 px-3 py-2.5">
                    <div className="flex min-w-0 items-center gap-3">
                      {included ? (
                        <Checkbox
                          id={rowId}
                          checked={!excluded.has(item.key)}
                          disabled={root || busy}
                          onCheckedChange={(checked) => onInclude(item.key, checked === true)}
                        />
                      ) : (
                        <Link2 className="text-muted-foreground size-4 shrink-0" aria-hidden />
                      )}
                      <ResourceMark item={item} identity={root ? rootIdentity : undefined} />
                      <Label
                        htmlFor={included ? rowId : undefined}
                        className="flex min-h-10 min-w-0 flex-1 flex-col items-start justify-center gap-0.5"
                      >
                        <span className="max-w-full truncate text-sm font-medium">{item.name}</span>
                        <span className="text-muted-foreground line-clamp-2 text-xs font-normal">
                          {root
                            ? t(
                                item.kind === "workflow"
                                  ? "workflowRootDefinition"
                                  : "rootDefinition",
                              )
                            : !included
                              ? t("referenceOnly")
                              : typeof model === "string"
                                ? model
                                : typeof description === "string" && description
                                  ? description
                                  : t("layerDefinition")}
                        </span>
                      </Label>
                    </div>
                    {included && !excluded.has(item.key) && (
                      <ExportLayers
                        layers={layers}
                        selected={layersByKey[item.key] ?? ["definition"]}
                        format={format}
                        disabled={busy}
                        knowledgeBase={item.kind === "knowledge_base"}
                        onChange={(selected) => onLayers(item.key, selected)}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </fieldset>
  );
}
