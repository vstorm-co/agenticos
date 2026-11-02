"use client";

import Link from "next/link";
import { Pencil, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Skill } from "@/types/providers";

/**
 * A skill's name and what it is for, with main's newest version beside it.
 *
 * Edit opens the same editor the list used to, on the line the page is showing;
 * a reader without edit access gets it read-only as Open.
 */
export function SkillPageHeader({
  skill,
  line,
  improveHref,
  onEdit,
}: {
  skill: Skill;
  /** The fork the page is showing, by name; null for main. */
  line: string | null;
  /** Where Improve opens the wizard for that line. */
  improveHref: string;
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
          {skill.can_edit && (
            <Button variant="outline" asChild data-tour="skill-improve">
              <Link href={improveHref}>
                <Sparkles className="h-4 w-4" aria-hidden />
                {line === null ? t("improve") : t("improveFork", { name: line })}
              </Link>
            </Button>
          )}
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
