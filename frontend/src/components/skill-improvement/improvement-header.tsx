"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { useSkillForks } from "@/hooks/use-skill-versions";
import { ROUTES } from "@/lib/constants";
import type { MergeKind } from "@/types/skill-merge";

/**
 * The page's title: improving the skill, or the merge a fork takes part in, named by
 * the fork once the skill's forks are read.
 */
export function SkillImprovementHeader({
  skillId,
  skillName,
  merge = null,
}: {
  skillId: string;
  skillName: string;
  merge?: { kind: MergeKind; forkId: string | null } | null;
}) {
  const t = useTranslations("skillImprovement");
  if (merge === null)
    return (
      <Header skillId={skillId} skillName={skillName} title={t("title", { name: skillName })} />
    );
  return <MergeHeader skillId={skillId} skillName={skillName} merge={merge} />;
}

function MergeHeader({
  skillId,
  skillName,
  merge,
}: {
  skillId: string;
  skillName: string;
  merge: { kind: MergeKind; forkId: string | null };
}) {
  const t = useTranslations("skillImprovement.mergeTitle");
  const { forks } = useSkillForks(skillId);
  const fork = forks.find((item) => item.id === merge.forkId)?.name;
  return (
    <Header
      skillId={skillId}
      skillName={skillName}
      title={fork ? t(`named.${merge.kind}`, { fork }) : t(`plain.${merge.kind}`)}
      crumb={t(`plain.${merge.kind}`)}
    />
  );
}

function Header({
  skillId,
  skillName,
  title,
  crumb,
}: {
  skillId: string;
  skillName: string;
  title: string;
  crumb?: string;
}) {
  const t = useTranslations("skillImprovement");
  return (
    <PageHeader
      title={title}
      breadcrumbs={[
        { label: t("skills"), href: ROUTES.SKILLS },
        { label: skillName, href: ROUTES.SKILL_DETAIL(skillId) },
        { label: crumb ?? t("heading") },
      ]}
    />
  );
}
