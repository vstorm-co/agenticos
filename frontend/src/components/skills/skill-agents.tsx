"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeftRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Badge, Button, DataTable, ListCard, type Column } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { SkillAgentList, SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { ChangeVersionDialog } from "./change-version-dialog";
import { LineChips } from "./line-chips";
import { bindingLabel, eachAgentOnce, isShown, readerKey, type ShownAgents } from "./skill-lines";

/** Each agent that uses the skill, the version it is served, and the way to move it. */
export function SkillAgents({
  skillId,
  skillName,
  agents,
  error,
  forks,
  shown,
  onShow,
}: {
  skillId: string;
  skillName: string;
  agents: SkillAgentList | undefined;
  error: unknown;
  forks: SkillFork[];
  shown: ShownAgents;
  onShow: (next: ShownAgents) => void;
}) {
  const t = useTranslations("skills.page");
  const tErrors = useTranslations("errors");
  const [changing, setChanging] = useState<SkillAgentUsage | null>(null);
  const items = agents?.items ?? [];
  const rows = items.filter((usage) => isShown(usage, shown));

  const columns: Column<SkillAgentUsage>[] = [
    {
      key: "agent",
      header: t("agentsTable.agent"),
      cell: (usage) => (
        <div className="flex min-w-0 items-center gap-2">
          <AgentAvatar
            agentId={usage.agent.id}
            slug={usage.agent.slug}
            hasAvatar={usage.agent.has_avatar}
            colorSlot={usage.agent.avatar_color}
            size="sm"
          />
          <div className="min-w-0">
            <Link
              href={ROUTES.AGENT_DETAIL(usage.agent.id)}
              className="block truncate font-medium hover:underline"
            >
              {usage.agent.name}
            </Link>
            {usage.via_specialist !== null && (
              <p className="text-muted-foreground truncate text-xs">
                {t("agentsTable.viaSpecialist", { name: usage.via_specialist })}
              </p>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "version",
      header: t("agentsTable.version"),
      cell: (usage) => <BindingCell usage={usage} />,
    },
    {
      key: "change",
      header: <span className="sr-only">{t("agentsTable.actions")}</span>,
      align: "right",
      cell: (usage) =>
        usage.can_change && !usage.draft_only && usage.via_specialist === null ? (
          <Button
            variant="outline"
            size="sm"
            data-tour="skill-change-version"
            onClick={() => setChanging(usage)}
            aria-label={t("changeVersion.for", { name: usage.agent.name })}
          >
            <ArrowLeftRight className="h-4 w-4" aria-hidden />
            <span className="max-sm:sr-only">{t("changeVersion.button")}</span>
          </Button>
        ) : null,
    },
  ];

  return (
    <ListCard
      title={t("tabs.agents")}
      counted={agents === undefined ? null : t("agentCount", { count: eachAgentOnce(rows).length })}
      controls={
        agents !== undefined && (
          <LineChips agents={items} forks={forks} value={shown} onChange={onShow} />
        )
      }
      headerTour="skill-agents"
    >
      <DataTable
        columns={columns}
        rows={agents === undefined && !error ? undefined : rows}
        getRowKey={readerKey}
        loading={agents === undefined && !error}
        error={error ? getErrorMessage(error, tErrors) : undefined}
        empty={<p className="text-muted-foreground p-4 text-sm">{t("agentsTable.empty")}</p>}
      />
      {(agents?.hidden ?? 0) > 0 && (
        <p className="text-muted-foreground px-4 py-3 text-xs">
          {t("agentsTable.hidden", { count: agents?.hidden ?? 0 })}
        </p>
      )}
      {changing !== null && (
        <ChangeVersionDialog
          skillId={skillId}
          skillName={skillName}
          usage={changing}
          forks={forks}
          onClose={() => setChanging(null)}
        />
      )}
    </ListCard>
  );
}

/** The served version, then where an environment or the draft says otherwise. */
function BindingCell({ usage }: { usage: SkillAgentUsage }) {
  const t = useTranslations("skills.page");
  return (
    <div className="space-y-0.5 text-sm">
      <p className="flex flex-wrap items-center gap-1.5">
        <span>{bindingLabel(t, usage.binding)}</span>
        {usage.draft_only && <Badge variant="outline">{t("agentsTable.draftOnly")}</Badge>}
      </p>
      {usage.environments.map((environment) => (
        <p key={environment.id} className="text-muted-foreground text-xs">
          {t("agentsTable.environment", {
            name: environment.name,
            binding: bindingLabel(t, environment.binding),
          })}
        </p>
      ))}
      {usage.draft_differs && !usage.draft_only && (
        <p className="text-muted-foreground text-xs">{t("agentsTable.draftDiffers")}</p>
      )}
    </div>
  );
}
