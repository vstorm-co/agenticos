"use client";

import { AlertTriangle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { AgentSpec } from "@/types/agents";

/** The one field every list here is read for; the rows are whatever the hooks hand over. */
type Row = { id: string };

interface StaleReferencesProps {
  spec: AgentSpec;
  collections: Row[];
  contextFiles: Row[];
  /** How many context files the organization holds - the list above may be a page of them. */
  contextTotal: number;
  skills: Row[];
  skillTotal: number;
  connections: Row[];
  catalog: { key: string }[];
  /** The spec with the stale references taken out, for the caller to save. */
  onRemove: (changes: Partial<AgentSpec>) => void;
  disabled?: boolean;
}

/** What a draft still names that the organization no longer has. */
export interface StaleReferenceSet {
  collection_ids: string[];
  context_ids: string[];
  skill_ids: string[];
  mcp_servers: AgentSpec["mcp_servers"];
}

/**
 * The spec's references that resolve to nothing, of every kind at once.
 *
 * A page of a list cannot say what is missing from the whole: where the
 * organization holds more context files or skills than the Builder loaded, those
 * two kinds are left alone rather than declared stale on the strength of one
 * page. Collections and connections arrive whole, and a catalog key is checked
 * against the whole curated catalog.
 */
export function staleReferences(
  spec: AgentSpec,
  known: Omit<StaleReferencesProps, "spec" | "onRemove" | "disabled">,
): StaleReferenceSet {
  const collections = new Set(known.collections.map((one) => one.id));
  const contextFiles = new Set(known.contextFiles.map((one) => one.id));
  const skills = new Set(known.skills.map((one) => one.id));
  const connections = new Set(known.connections.map((one) => one.id));
  const catalog = new Set(known.catalog.map((one) => one.key));
  const contextComplete = known.contextTotal <= known.contextFiles.length;
  const skillsComplete = known.skillTotal <= known.skills.length;
  return {
    collection_ids: spec.collection_ids.filter((id) => !collections.has(id)),
    context_ids: contextComplete ? spec.context_ids.filter((id) => !contextFiles.has(id)) : [],
    skill_ids: skillsComplete ? spec.skill_ids.filter((id) => !skills.has(id)) : [],
    mcp_servers: spec.mcp_servers.filter((ref) =>
      ref.account === "organization"
        ? !connections.has(ref.connection_id)
        : !catalog.has(ref.catalog_key),
    ),
  };
}

/**
 * One notice for every reference the draft holds to something that is gone, with
 * the one button that clears them.
 *
 * Publish refuses a spec that names a deleted collection, context file, skill or
 * connection, and it is right to: a run would resolve the id to nothing. But the
 * refusal used to be the first anybody heard of it, and the id it named was
 * shown only inside the panel of the capability that reads it - which an agent
 * with that capability switched off never opens. Somebody who had deleted a
 * knowledge base months ago met "Collection not found: <uuid>" on an agent with
 * no knowledge tool at all, and nowhere to clear it. This sits above the tabs,
 * whatever tab is open, and clears them in one edit of the draft.
 */
export function StaleReferences({ spec, onRemove, disabled, ...known }: StaleReferencesProps) {
  const t = useTranslations("agents");
  const locale = useLocale();
  const stale = staleReferences(spec, known);
  const parts = [
    stale.collection_ids.length && t("staleCollections", { count: stale.collection_ids.length }),
    stale.context_ids.length && t("staleContext", { count: stale.context_ids.length }),
    stale.skill_ids.length && t("staleSkills", { count: stale.skill_ids.length }),
    stale.mcp_servers.length && t("staleServers", { count: stale.mcp_servers.length }),
  ].filter((part): part is string => typeof part === "string");
  if (parts.length === 0) return null;

  const remove = () => {
    const gone = new Set([...stale.collection_ids, ...stale.context_ids, ...stale.skill_ids]);
    const staleServers = new Set(stale.mcp_servers);
    onRemove({
      collection_ids: spec.collection_ids.filter((id) => !gone.has(id)),
      context_ids: spec.context_ids.filter((id) => !gone.has(id)),
      skill_ids: spec.skill_ids.filter((id) => !gone.has(id)),
      mcp_servers: spec.mcp_servers.filter((ref) => !staleServers.has(ref)),
    });
  };

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm"
    >
      <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" aria-hidden />
      <span className="min-w-0 flex-1">
        {t("staleReferences", { list: new Intl.ListFormat(locale).format(parts) })}
      </span>
      <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={remove}>
        {t("removeStaleReferences")}
      </Button>
    </div>
  );
}
