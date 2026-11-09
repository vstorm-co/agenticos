"use client";

import { useId } from "react";
import Link from "next/link";
import { GitBranch, GitMerge, MoreHorizontal, Pencil, Sparkles, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui";
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
 *
 * On a fork the bar keeps what is done there often - Improve, Catch up, Edit - and the
 * rare ones (moving it to main, returning its agents, a new fork, deleting the skill)
 * wait under More, so seven buttons do not wrap onto a second row.
 */
/** Where the fork shown merges with main. */
export interface Merges {
  fork: string;
  catchUp: string | null;
  toMain: string | null;
  /** The fork has no version of its own, so neither merge has anything to carry. */
  empty?: boolean;
}

export function SkillPageHeader({
  skill,
  line,
  improveHref,
  merges = null,
  onReturn = null,
  onEdit,
  opening = false,
  onFork,
  onDelete = null,
}: {
  skill: Skill;
  /** The fork the page is showing, by name; null for main. */
  line: string | null;
  /** Where Improve opens the wizard for that line. */
  improveHref: string;
  /**
   * Where the wizard merges the fork shown with main; each null where there is nothing
   * to merge. A fork with no version of its own has nothing yet, and says so.
   */
  merges?: Merges | null;
  /** Returns the fork shown to main when it has nothing of its own to merge. */
  onReturn?: { fork: string; open: () => void } | null;
  onEdit: () => void;
  /** The editor is on its way after a press of Edit. */
  opening?: boolean;
  /** Offered to an editor once main has a version to start from. */
  onFork: (() => void) | null;
  /** Deletes the whole skill, every line with it; offered to an editor. */
  onDelete?: (() => void) | null;
}) {
  const t = useTranslations("skills.page");
  const { can } = usePermissions();
  // Improving and merging read the line's runs, so they are an editor's who may read them.
  const merger = skill.can_edit === true && can(Perm.runsView);
  const rare = merger && (merges?.toMain || merges?.empty || onReturn);
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
          {merger && (
            <Button variant="outline" asChild data-tour="skill-improve">
              <Link href={improveHref}>
                <Sparkles className="h-4 w-4" aria-hidden />
                {line === null ? t("improve") : t("improveFork", { name: line })}
              </Link>
            </Button>
          )}
          {merger && merges?.empty && (
            <NothingToMerge label={t("catchUp", { name: merges.fork })} />
          )}
          {merger && merges?.catchUp && (
            <Button variant="outline" asChild data-tour="skill-catch-up">
              <Link href={merges.catchUp}>
                <GitMerge className="h-4 w-4" aria-hidden />
                {t("catchUp", { name: merges.fork })}
              </Link>
            </Button>
          )}
          {line === null && onFork && (
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
          {line === null && onDelete && (
            <Button
              variant="outline"
              className="text-destructive hover:text-destructive"
              onClick={onDelete}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
              {t("deleteSkill.button")}
            </Button>
          )}
          {line !== null && (rare || onFork || onDelete) && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label={t("more")}>
                  <MoreHorizontal className="h-4 w-4" aria-hidden />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {merger && merges?.toMain && (
                  <DropdownMenuItem asChild>
                    <Link href={merges.toMain}>
                      <GitMerge className="h-4 w-4" aria-hidden />
                      {t("toMain", { name: merges.fork })}
                    </Link>
                  </DropdownMenuItem>
                )}
                {merger && merges?.empty && (
                  <DropdownMenuItem disabled title={t("nothingToMerge")}>
                    <GitMerge className="h-4 w-4" aria-hidden />
                    {t("toMain", { name: merges.fork })}
                  </DropdownMenuItem>
                )}
                {merger && onReturn && (
                  <DropdownMenuItem onSelect={onReturn.open}>
                    <GitMerge className="h-4 w-4" aria-hidden />
                    {t("returnFork.button", { name: onReturn.fork })}
                  </DropdownMenuItem>
                )}
                {onFork && (
                  <DropdownMenuItem onSelect={onFork}>
                    <GitBranch className="h-4 w-4" aria-hidden />
                    {t("newFork.button")}
                  </DropdownMenuItem>
                )}
                {onDelete && (
                  <DropdownMenuItem
                    onSelect={onDelete}
                    className="text-destructive focus:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                    {t("deleteSkill.button")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </>
      }
    />
  );
}

/**
 * Catching up, held until the fork has a version of its own to carry. Marked rather
 * than disabled, so the pointer and the keyboard both reach the reason.
 */
function NothingToMerge({ label }: { label: string }) {
  const t = useTranslations("skills.page");
  const hint = useId();
  return (
    <TooltipProvider>
      <span id={hint} className="sr-only">
        {t("nothingToMerge")}
      </span>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="outline"
            aria-disabled
            aria-describedby={hint}
            className="cursor-not-allowed opacity-50"
          >
            <GitMerge className="h-4 w-4" aria-hidden />
            {label}
          </Button>
        </TooltipTrigger>
        <TooltipContent>{t("nothingToMerge")}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
