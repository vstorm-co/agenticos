"use client";

import { AlertTriangle, BookOpen, Building2, Database, FileText, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Card, CardContent } from "@/components/ui";
import { useKnowledgeReach } from "@/hooks";
import type { KnowledgeSource } from "@/types/agents";

const KIND_ICON = { collection: Database, skill: BookOpen, context: FileText } as const;

/**
 * Where this agent's knowledge comes from, and who it reaches (#2072).
 *
 * A department keeps its skills, context and knowledge bases by sharing them with
 * its group. Binding one to an agent shared more widely is allowed, and the
 * agent then answers people from it who could not open it themselves - so each
 * source says whose it is, and one the agent reaches further than is flagged.
 * Nothing renders until the agent binds a source.
 */
export function KnowledgeReach({ agentId }: { agentId: string }) {
  const t = useTranslations("agents");
  const { reach } = useKnowledgeReach(agentId);
  if (!reach || reach.sources.length === 0) return null;
  const flagged = reach.sources.filter((source) => source.reaches_fewer_than_agent);

  return (
    <Card data-tour="agent-knowledge-reach">
      <CardContent className="space-y-3 p-5">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{t("knowledgeReachTitle")}</span>
          <span className="text-muted-foreground">{t("knowledgeReachAgent")}</span>
          <Audience whole={reach.whole_organization} groups={reach.groups} />
        </div>
        {flagged.length > 0 && (
          <p className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-xs">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden />
            {t("knowledgeReachWarning", { count: flagged.length })}
          </p>
        )}
        <ul className="space-y-1.5">
          {reach.sources.map((source) => (
            <SourceRow key={`${source.kind}-${source.id}`} source={source} />
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function SourceRow({ source }: { source: KnowledgeSource }) {
  const t = useTranslations("agents");
  const Icon = KIND_ICON[source.kind];
  return (
    <li className="flex flex-wrap items-center gap-2 text-sm">
      <Icon className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
      <span className="font-medium">{source.name}</span>
      <Audience whole={source.whole_organization} groups={source.groups} />
      {source.reaches_fewer_than_agent && (
        <Badge variant="outline" className="border-amber-500/50 text-amber-700 dark:text-amber-400">
          {t("knowledgeReachNarrower")}
        </Badge>
      )}
    </li>
  );
}

/** Who something reaches, as chips: the organization, its groups, or only its people. */
function Audience({ whole, groups }: { whole: boolean; groups: string[] }) {
  const t = useTranslations("agents");
  if (whole) {
    return (
      <Badge variant="secondary" className="gap-1">
        <Building2 className="h-3 w-3" aria-hidden />
        {t("knowledgeReachEveryone")}
      </Badge>
    );
  }
  if (groups.length === 0) {
    return <Badge variant="secondary">{t("knowledgeReachPeople")}</Badge>;
  }
  return (
    <>
      {groups.map((group) => (
        <Badge key={group} variant="secondary" className="gap-1">
          <Users className="h-3 w-3" aria-hidden />
          {group}
        </Badge>
      ))}
    </>
  );
}
