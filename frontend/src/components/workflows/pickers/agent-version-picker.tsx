"use client";

import Link from "next/link";
import { AlertTriangle, Plus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Badge,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents, useAllAgentVersions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { Uuid } from "@/lib/workflows/types";

/**
 * Which agent, pinned to which version, a workflow node runs.
 *
 * A workflow never runs "the agent's latest" - it pins one immutable version, so
 * a published workflow keeps behaving as it did when it was published even after
 * the agent is edited. The pin is two ids in the node's `config`, `agent_id` and
 * `version_id`, and this is the one control that writes them together.
 */
export interface AgentVersionRef {
  /** The chosen agent, or null while none is. */
  agent_id: Uuid | null;
  /** The pinned version of that agent, or null while none is. */
  version_id: Uuid | null;
}

export interface AgentVersionPickerProps {
  value: AgentVersionRef;
  onChange: (next: AgentVersionRef) => void;
  disabled?: boolean;
  /** A validation message from the property panel, shown under the control. */
  error?: string;
}

/**
 * Two steps, because the version is meaningless without the agent and stale the
 * moment the agent changes. Choosing an agent therefore *clears* the pinned
 * version (the #1781 lab finding): keeping the old version id would pin a version
 * belonging to a different agent, which the graph would carry until publish
 * refused it. The version step stays disabled until an agent is chosen, and a
 * chosen agent with no version pinned is surfaced as unfinished rather than
 * silently defaulted.
 */
export function AgentVersionPicker({ value, onChange, disabled, error }: AgentVersionPickerProps) {
  const t = useTranslations("workflows");
  const locale = useLocale();
  const { agents, isLoading: agentsLoading } = useAgents();
  const { versions, isLoading: versionsLoading } = useAllAgentVersions(value.agent_id);

  const chosenAgent = agents.find((agent) => agent.id === value.agent_id);
  // An id that names no agent the caller can see: named rather than dropped, the
  // same reason `collection-picker` keeps an orphaned id visible - it is still in
  // the graph, and publish is otherwise where it first surfaces.
  const agentOrphaned = value.agent_id !== null && !agentsLoading && chosenAgent === undefined;
  const versionMissing = value.agent_id !== null && value.version_id === null;
  // A pinned version id that names no version the agent still publishes: surfaced,
  // not dropped, for the same reason as the orphaned agent above - it is in the
  // graph and publish is otherwise where it first surfaces.
  const versionOrphaned =
    value.version_id !== null &&
    !versionsLoading &&
    !versions.some((version) => version.id === value.version_id);

  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>{t("pickerAgentLabel")}</Label>
        <Select
          value={value.agent_id ?? ""}
          onValueChange={(agentId) => onChange({ agent_id: agentId, version_id: null })}
          disabled={disabled}
        >
          <SelectTrigger aria-label={t("pickerAgentLabel")}>
            <SelectValue placeholder={t("pickerAgentPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {agents.map((agent) => (
              // The face, in the list and the field alike, and the description
              // beside it in the list, are what tell two agents apart.
              <SelectItem
                key={agent.id}
                value={agent.id}
                textValue={agent.name}
                trailing={
                  agent.description && (
                    <span className="text-muted-foreground ml-3 max-w-[55%] truncate text-xs">
                      {agent.description}
                    </span>
                  )
                }
              >
                <span className="flex min-w-0 items-center gap-2">
                  <AgentAvatar
                    agentId={agent.id}
                    slug={agent.slug}
                    hasAvatar={agent.has_avatar}
                    colorSlot={agent.avatar_color}
                    size="sm"
                  />
                  <span className="truncate">{agent.name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {agents.length === 0 && !agentsLoading && (
          <p className="text-muted-foreground text-xs">{t("pickerAgentsEmpty")}</p>
        )}
        {agentOrphaned && (
          <p className="text-foreground/70 flex items-center gap-1.5 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {t("pickerAgentOrphaned")} <span className="font-mono break-all">{value.agent_id}</span>
          </p>
        )}
      </div>

      <div className="space-y-1.5">
        <Label>{t("pickerVersionLabel")}</Label>
        <Select
          value={value.version_id ?? ""}
          onValueChange={(versionId) =>
            onChange({ agent_id: value.agent_id, version_id: versionId })
          }
          disabled={disabled || value.agent_id === null || agentOrphaned}
        >
          <SelectTrigger aria-label={t("pickerVersionLabel")}>
            <SelectValue placeholder={t("pickerVersionPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {versions.map((version) => (
              <SelectItem
                key={version.id}
                value={version.id}
                textValue={t("pickerVersionNumber", { version: version.version })}
                trailing={
                  // When and why it was published, to pin the right one.
                  <span className="text-muted-foreground ml-3 truncate text-xs">
                    {[
                      version.created_at && formatDateTime(version.created_at, locale),
                      version.note,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                }
              >
                <span className="flex items-center gap-2">
                  {t("pickerVersionNumber", { version: version.version })}
                  {version.id === chosenAgent?.current_version_id && (
                    <Badge variant="outline">{t("pickerVersionLive")}</Badge>
                  )}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {value.agent_id !== null && !agentOrphaned && versions.length === 0 && !versionsLoading && (
          <p className="text-muted-foreground text-xs">{t("pickerVersionEmpty")}</p>
        )}
        {versionMissing && !agentOrphaned && versions.length > 0 && (
          <p className="text-foreground/70 flex items-center gap-1.5 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {t("pickerVersionRequired")}
          </p>
        )}
        {versionOrphaned && !agentOrphaned && versions.length > 0 && (
          <p className="text-foreground/70 flex items-center gap-1.5 text-xs">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            {t("pickerVersionOrphaned")}{" "}
            <span className="font-mono break-all">{value.version_id}</span>
          </p>
        )}
      </div>

      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}

      <Link
        href={ROUTES.AGENTS}
        className="text-muted-foreground inline-flex items-center gap-1.5 text-xs underline underline-offset-4"
      >
        <Plus className="h-3.5 w-3.5" />
        {t("pickerAgentCreate")}
      </Link>
    </div>
  );
}
