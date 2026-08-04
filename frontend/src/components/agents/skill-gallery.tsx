"use client";

import Link from "next/link";
import { BookOpen, Check, Plus } from "lucide-react";

import { Badge, Pager, SearchInput, useListControls } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { SkillSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

interface SkillGalleryProps {
  skills: SkillSummary[];
  /**
   * How many the organization has, which may exceed what was fetched. Only the
   * orphan warning depends on the difference - see below.
   */
  total: number;
  /** `spec.skill_ids`. */
  selectedIds: string[];
  onToggle: (skillId: string) => void;
  disabled?: boolean;
}

/**
 * Every skill the organization has written, as a gallery to pick from.
 *
 * A gallery rather than a checkbox list because a skill is chosen on what it
 * says: the description is the whole basis for deciding whether this agent
 * should have it, and a list that truncates it to fit a row makes the decision
 * on a name alone.
 *
 * Skills that no longer exist are named rather than dropped. An id that
 * silently vanishes from a form is an id that silently vanishes from the spec,
 * and this one refuses at publish rather than at edit - so the Builder has to
 * say it is there.
 */
export function SkillGallery({
  skills,
  total,
  selectedIds,
  onToggle,
  disabled,
}: SkillGalleryProps) {
  const t = useTranslations("agents");
  const chosen = new Set(selectedIds);
  const known = new Set(skills.map((skill) => skill.id));
  // Only when this is the whole set. Against a page of it, every skill the
  // caller did not fetch reads as one the organization deleted - an accusation
  // that publishing will be refused, made about a skill that is fine.
  const orphaned = skills.length >= total ? selectedIds.filter((id) => !known.has(id)) : [];

  const list = useListControls({
    items: skills,
    matches: (skill, query) =>
      skill.name.toLowerCase().includes(query) || skill.description.toLowerCase().includes(query),
  });

  if (skills.length === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <BookOpen className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-muted-foreground mt-2 text-sm">{t("organizationHasWrittenNo")}</p>
        <Link
          href={ROUTES.SKILLS}
          className="mt-3 inline-flex items-center gap-1.5 text-sm underline underline-offset-4"
        >
          <Plus className="h-3.5 w-3.5" />
          {t("writeOne")}
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {skills.length > 8 && (
        <SearchInput value={list.query} onChange={list.setQuery} placeholder={t("searchSkills")} />
      )}

      <div className="grid gap-2 sm:grid-cols-2">
        {list.visible.map((skill) => {
          const isOn = chosen.has(skill.id);
          return (
            <button
              key={skill.id}
              type="button"
              role="checkbox"
              aria-checked={isOn}
              aria-label={skill.name}
              disabled={disabled}
              onClick={() => onToggle(skill.id)}
              className={cn(
                t("flexItemsStartGap3"),
                isOn ? "border-brand bg-brand/5" : "hover:border-foreground/20",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border",
                  isOn ? "border-brand bg-brand text-brand-foreground" : "border-input",
                )}
              >
                {isOn && <Check className="h-3 w-3" />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm font-medium">{skill.name}</span>
                  {!skill.enabled && <Badge variant="outline">{t("disabled")}</Badge>}
                </span>
                <span className="text-muted-foreground mt-1 block text-sm">
                  {skill.description}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <Pager
        page={list.page}
        pageCount={list.pageCount}
        matched={list.matched}
        total={list.total}
        onPage={list.setPage}
        noun="skills"
      />

      {orphaned.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("orphanedSkills", { count: orphaned.length })}{" "}
          <span className="font-mono break-all">{orphaned.join(", ")}</span>
        </p>
      )}

      <p className="text-muted-foreground text-xs">
        The agent loads a skill only when it decides one is relevant, so twenty skills cost almost
        nothing in context.{" "}
        <Link href={ROUTES.SKILLS} className="underline underline-offset-4">
          {t("manageSkills")}
        </Link>
      </p>
    </div>
  );
}
