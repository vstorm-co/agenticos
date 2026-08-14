"use client";

import { useTranslations } from "next-intl";

import { RUN_LABEL } from "@/components/agents/status-badge";
import { SurfaceIcon } from "@/components/runs/surface-icon";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { useAgents, useAgentVersions, useMembers, usePermissions } from "@/hooks";
import { useOrgStore } from "@/stores";
import { Perm } from "@/types/permissions";
import type { RunStatus } from "@/types/runs";

/** What the status filter offers, in the order the badge vocabulary lists them. */
const STATUSES = Object.keys(RUN_LABEL) as RunStatus[];

/** `RunSurface` on the backend - every value something assigns, none invented. */
export const SURFACES = ["web", "embed", "api", "slack", "telegram", "mattermost"] as const;

/** Every narrowing the bar owns. "all" is the unfiltered value throughout. */
export interface RunFilters {
  status: RunStatus | "all" | "problems";
  surface: string;
  rated: "all" | "up" | "down";
  userId: string;
  versionId: string;
}

export const DEFAULT_RUN_FILTERS: RunFilters = {
  status: "all",
  surface: "all",
  rated: "all",
  userId: "all",
  versionId: "all",
};

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
  onChange,
  agentId,
  onAgentChange,
}: {
  filters: RunFilters;
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
            <SelectItem key={entry} value={entry} className="font-mono text-xs">
              <span className="flex items-center gap-1.5">
                <SurfaceIcon surface={entry} />
                {entry}
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
        {agents.map((agent) => (
          <SelectItem key={agent.id} value={agent.id}>
            {agent.name}
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
        {members.map((member) => (
          <SelectItem key={member.user_id} value={member.user_id}>
            {member.full_name ?? member.email}
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
