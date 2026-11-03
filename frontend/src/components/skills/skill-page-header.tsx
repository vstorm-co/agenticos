"use client";

import { Pencil } from "lucide-react";
import { useTranslations } from "next-intl";

import { ImproveSkillButton } from "@/components/authoring/improve-skill-button";
import { PageHeader } from "@/components/dashboard/page-header";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Skill } from "@/types/providers";

/**
 * A skill's name and what it is for, with main's newest version beside it.
 *
 * Edit opens the skill's editor on the line the page is showing; a reader without
 * edit access gets it read-only as Open.
 */
export function SkillPageHeader({
  skill,
  line,
  onEdit,
}: {
  skill: Skill;
  /** The fork the page is showing, by name; null for main. */
  line: string | null;
  onEdit: () => void;
}) {
  const t = useTranslations("skills.page");
  return (
    <PageHeader
      title={<span className="font-mono">{skill.name}</span>}
      description={skill.description}
      descriptionMode="summary"
      breadcrumbs={[{ label: t("skills"), href: ROUTES.SKILLS }, { label: skill.name }]}
      badges={
        <>
          <Badge variant="outline">{t("mainVersion", { number: skill.version })}</Badge>
          {skill.forks ? (
            <Badge variant="outline">{t("forkCount", { count: skill.forks })}</Badge>
          ) : null}
        </>
      }
      actions={
        <>
          {skill.can_edit && <ImproveSkillButton skillId={skill.id} />}
          <Button data-tour="skill-edit" onClick={onEdit}>
            <Pencil className="h-4 w-4" aria-hidden />
            {skill.can_edit
              ? line === null
                ? t("editSkill")
                : t("editFork", { name: line })
              : t("open")}
          </Button>
        </>
      }
    />
  );
}
