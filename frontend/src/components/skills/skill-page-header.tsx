"use client";

import Link from "next/link";
import { GitBranch, GitMerge, Pencil, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Badge, Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { Skill } from "@/types/providers";

/**
 * A skill's name and what it is for, with main's newest version beside it.
 *
 * Edit opens the skill's editor on the line the page is showing; a reader without
 * edit access gets it read-only as Open. Improve reads the line's runs, so it is
 * offered to an editor who may also read them, and so are catching the fork shown up
 * with main and moving it to main, which are checked the same way. New fork starts a
 * line of its own from main's newest version.
 */
export function SkillPageHeader({
  skill,
  line,
  improveHref,
  merges = null,
  onEdit,
  opening = false,
  onFork,
}: {
  skill: Skill;
  /** The fork the page is showing, by name; null for main. */
  line: string | null;
  /** Where Improve opens the wizard for that line. */
  improveHref: string;
  /** Where the wizard merges the fork shown with main; each null where there is nothing to merge. */
  merges?: { fork: string; catchUp: string | null; toMain: string | null } | null;
  onEdit: () => void;
  /** The editor is on its way after a press of Edit. */
  opening?: boolean;
  /** Offered to an editor once main has a version to start from. */
  onFork: (() => void) | null;
}) {
  const t = useTranslations("skills.page");
  const { can } = usePermissions();
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
          {skill.can_edit && can(Perm.runsView) && (
            <>
              <Button variant="outline" asChild data-tour="skill-improve">
                <Link href={improveHref}>
                  <Sparkles className="h-4 w-4" aria-hidden />
                  {line === null ? t("improve") : t("improveFork", { name: line })}
                </Link>
              </Button>
              {merges?.catchUp && (
                <Button variant="outline" asChild data-tour="skill-catch-up">
                  <Link href={merges.catchUp}>
                    <GitMerge className="h-4 w-4" aria-hidden />
                    {t("catchUp", { name: merges.fork })}
                  </Link>
                </Button>
              )}
              {merges?.toMain && (
                <Button variant="outline" asChild>
                  <Link href={merges.toMain}>
                    <GitMerge className="h-4 w-4" aria-hidden />
                    {t("toMain", { name: merges.fork })}
                  </Link>
                </Button>
              )}
            </>
          )}
          {onFork && (
            <Button variant="outline" data-tour="skill-new-fork" onClick={onFork}>
              <GitBranch className="h-4 w-4" aria-hidden />
              {t("newFork.button")}
            </Button>
          )}
          <Button data-tour="skill-edit" loading={opening} onClick={onEdit}>
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
