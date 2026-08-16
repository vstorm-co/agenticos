"use client";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { RUN_LABEL } from "@/components/agents/status-badge";
import { displayName } from "@/components/orgs/member-identity";
import { SurfaceIcon, surfaceLabel } from "@/components/runs/surface-icon";
import {
  EntityAvatar,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents, useAgentVersions, useMembers, usePermissions, useUsageStats } from "@/hooks";
import type { Period } from "@/lib/dashboard/period";
import { DEFAULT_RUN_FILTERS, type RunFilters } from "@/lib/runs/filter-params";
import { useOrgStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { RunStatus } from "@/types/runs";

/** What the status filter offers, in the order the badge vocabulary lists them. */
const STATUSES = Object.keys(RUN_LABEL) as RunStatus[];

/** `RunSurface` on the backend - every value something assigns, none invented. */
export const SURFACES = ["web", "embed", "api", "slack", "telegram", "mattermost"] as const;

// The shape and its defaults live in `lib/runs/filter-params.ts`, with the two
// directions of the URL round-trip - a narrowing that travels in a link cannot
// have its vocabulary defined inside the component that happens to draw it.
// Re-exported so the bar is still the one import a caller needs.
export { DEFAULT_RUN_FILTERS, type RunFilters };

/**
 * The run history's filter row - every narrowing the backend answers, as one
 * strip of selects.
 *
 * Each select is a server-side narrowing over the whole windowed history,
 * never a client-side pass over one page - the failed Slack run of the month
 * is not in whichever fifty rows a feed returned.
 *
 * The agent and version selects need `agents:view` to fill their options, so a
 * caller without it is not shown them at all - rendered, they would be a menu
 * whose request 403s. They live in subcomponents because a hook cannot sit
 * behind an `if`, and their queries must not fire for a caller the answer
 * would refuse. The person select's options are the member list, which any
 * member may read.
 */
export function RunFilterBar({
  filters,
  period,
  onChange,
  agentId,
  onAgentChange,
}: {
  filters: RunFilters;
  /** The window - the model facet offers the labels it actually holds. */
  period: Period;
  onChange: (filters: RunFilters) => void;
  agentId: string | null;
  onAgentChange: (agentId: string | null) => void;
}) {
  const t = useTranslations("pages.runs");
  const tAgents = useTranslations("agents");
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const set = (patch: Partial<RunFilters>) => onChange({ ...filters, ...patch });

  return (
    <>
      <Select
        value={filters.status}
        onValueChange={(value) => set({ status: value as RunFilters["status"] })}
      >
        <SelectTrigger className="h-8 w-[170px]" aria-label={t("statusFilter")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("anyStatus")}</SelectItem>
          <SelectItem value="problems">{t("problemsOnly")}</SelectItem>
          {STATUSES.map((entry) => (
            <SelectItem key={entry} value={entry}>
              {tAgents(RUN_LABEL[entry])}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Select value={filters.surface} onValueChange={(value) => set({ surface: value })}>
        <SelectTrigger className="h-8 w-[150px]" aria-label={t("surfaceFilter")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("anySurface")}</SelectItem>
          {SURFACES.map((entry) => (
            <SelectItem key={entry} value={entry}>
              <span className="flex items-center gap-1.5">
                <SurfaceIcon surface={entry} />
                {surfaceLabel(entry, t)}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {/* Both directions, not only down: "what did people like" is how a good
          version is told from a lucky one, and the backend has answered
          rated=up all along. */}
      <Select
        value={filters.rated}
        onValueChange={(value) => set({ rated: value as RunFilters["rated"] })}
      >
        <SelectTrigger className="h-8 w-[150px]" aria-label={t("ratingFilter")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("anyRating")}</SelectItem>
          <SelectItem value="up">{t("ratedUp")}</SelectItem>
          <SelectItem value="down">{t("ratedDown")}</SelectItem>
        </SelectContent>
      </Select>
      <ModelSelect
        period={period}
        model={filters.model}
        onModelChange={(model) => set({ model })}
      />
      {can(Perm.agentsView) && <AgentSelect agentId={agentId} onAgentChange={onAgentChange} />}
      {activeOrgId !== null && (
        <PersonSelect
          orgId={activeOrgId}
          userId={filters.userId}
          onUserChange={(userId) => set({ userId })}
        />
      )}
      {agentId !== null && can(Perm.agentsView) && (
        <VersionSelect
          agentId={agentId}
          versionId={filters.versionId}
          onVersionChange={(versionId) => set({ versionId })}
        />
      )}
    </>
  );
}

/**
 * Which model answered, offered as the labels this window actually recorded.
 *
 * Not the model catalog: a run stores the label it ran with, and a profile that
 * has since been renamed or deleted still has runs behind it. The vocabulary
 * therefore comes from the same `by_model` block the dashboard's card counts,
 * which is what makes "the runs behind this bar" the same set on both screens.
 * A window with one model needs no select at all.
 */
function ModelSelect({
  period,
  model,
  onModelChange,
}: {
  period: Period;
  model: string;
  onModelChange: (model: string) => void;
}) {
  const t = useTranslations("pages.runs");
  const { usage } = useUsageStats({ from: period.from, to: period.to });
  const labels = (usage?.by_model ?? [])
    .map((row) => row.model_label)
    .filter((label): label is string => label !== null);
  // Whatever a link narrowed to, even if the window holds no runs of it - the
  // control has to be able to say what it is showing, and to clear it.
  const options = labels.includes(model) || model === "all" ? labels : [...labels, model];
  if (options.length < 2 && model === "all") return null;

  return (
    <Select value={model} onValueChange={onModelChange}>
      <SelectTrigger className="h-8 w-[190px]" aria-label={t("modelFilter")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t("anyModel")}</SelectItem>
        {options.map((label) => (
          <SelectItem key={label} value={label}>
            {label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function AgentSelect({
  agentId,
  onAgentChange,
}: {
  agentId: string | null;
  onAgentChange: (agentId: string | null) => void;
}) {
  const t = useTranslations("pages.runs");
  const { agents } = useAgents();

  return (
    <Select
      value={agentId ?? "all"}
      onValueChange={(value) => onAgentChange(value === "all" ? null : value)}
    >
      <SelectTrigger className="h-8 w-[180px]" aria-label={t("agentFilter")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t("anyAgent")}</SelectItem>
        {/* The face beside the name, the same presentation every list of
            agents draws - initials when nobody uploaded a picture. */}
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            <span className="flex items-center gap-2">
              {/* Decorative beside the name it initials - in the accessible
                  name the option would read "SA Support agent". */}
              <span aria-hidden>
                <AgentAvatar
                  agentId={agent.id}
                  name={agent.name}
                  hasAvatar={agent.has_avatar ?? false}
                  size="sm"
                  className="h-5 w-5"
                />
              </span>
              {agent.name}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function PersonSelect({
  orgId,
  userId,
  onUserChange,
}: {
  orgId: string;
  userId: string;
  onUserChange: (userId: string) => void;
}) {
  const t = useTranslations("pages.runs");
  const { members } = useMembers(orgId);

  return (
    <Select value={userId} onValueChange={onUserChange}>
      <SelectTrigger className="h-8 w-[180px]" aria-label={t("personFilter")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t("anyPerson")}</SelectItem>
        {/* The application's one way of drawing a person - a face, initials
            when nobody uploaded one, the name over the address (see
            MemberIdentity, compacted to a menu row). */}
        {members.map((member) => (
          <SelectItem key={member.user_id} value={member.user_id}>
            <span className="flex items-center gap-2">
              <EntityAvatar
                seed={member.user_id}
                name={member.full_name || member.email}
                imageSrc={`/api/users/avatar/${member.user_id}`}
                className="h-5 w-5 shrink-0 text-[9px]"
                ariaHidden
              />
              {displayName(member)}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function VersionSelect({
  agentId,
  versionId,
  onVersionChange,
}: {
  agentId: string;
  versionId: string;
  onVersionChange: (versionId: string) => void;
}) {
  const t = useTranslations("pages.runs");
  const { versions } = useAgentVersions(agentId);

  return (
    <Select value={versionId} onValueChange={onVersionChange}>
      <SelectTrigger className="h-8 w-[140px]" aria-label={t("versionFilter")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="all">{t("anyVersion")}</SelectItem>
        {versions.map((version) => (
          <SelectItem key={version.id} value={version.id} className="tabular-nums">
            v{version.version}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
