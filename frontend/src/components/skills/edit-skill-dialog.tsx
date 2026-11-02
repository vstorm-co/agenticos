"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { categorySuggestions } from "@/components/skills/category-input";
import { SkillWorkbench } from "@/components/skills/skill-workbench";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Skeleton,
} from "@/components/ui";
import { useSkill, useSkills } from "@/hooks";
import { useSkillVersion, useSkillVersionWrites } from "@/hooks/use-skill-versions";
import type { SkillEdit } from "@/hooks/use-skills";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/providers";
import type { SkillFork } from "@/types/skill-versions";

/**
 * The skill's editor, saving a new version on the line the page is showing.
 *
 * On main it is the whole skill; on a fork it is the fork's newest text, and only
 * that text - the files and the category are main's.
 */
export function EditSkillDialog({
  skill,
  fork,
  followers,
  onClose,
  onDelete,
}: {
  skill: Skill;
  fork: SkillFork | null;
  /** How many agents follow the line being edited, and so get the save at once. */
  followers: number;
  onClose: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("skills.page.edit");
  const tErrors = useTranslations("errors");
  const { categories, suggestedCategories } = useSkills({ limit: 1 });
  const { save } = useSkill(skill.id);
  const { edit } = useSkillVersionWrites(skill.id);
  const forkVersionId = fork === null ? null : (fork.latest?.id ?? fork.base.id);
  const forkText = useSkillVersion(skill.id, forkVersionId);
  const baseVersionId = forkVersionId ?? skill.latest_version?.id ?? null;
  const shown =
    fork === null || forkText.version === undefined
      ? skill
      : { ...skill, description: forkText.version.description, content: forkText.version.content };
  const next =
    fork === null
      ? (skill.latest_version?.number ?? skill.version) + 1
      : (fork.latest?.number ?? 0) + 1;

  async function handleSave(change: SkillEdit) {
    try {
      const textChanged =
        change.description !== shown.description || change.content !== shown.content;
      if (textChanged && baseVersionId !== null) {
        await edit.mutateAsync({
          forkId: fork?.id ?? null,
          baseVersionId,
          description: change.description,
          content: change.content,
        });
        toast.success(t("saved", { number: next }));
      }
      // The category is the skill's, not a version's, so it is saved beside the text.
      if (fork === null && change.category !== skill.category) {
        await save.mutateAsync({ category: change.category });
      }
      onClose();
    } catch (refusal) {
      toast.error(getErrorMessage(refusal, tErrors));
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn(DIALOG_FILL, DIALOG_CANVAS, "max-md:overflow-y-auto")}>
        <DialogHeader>
          <DialogTitle className="font-mono">
            {fork === null ? skill.name : t("forkTitle", { skill: skill.name, name: fork.name })}
          </DialogTitle>
          <DialogDescription>{t("nameHowModelRefers")}</DialogDescription>
        </DialogHeader>
        {fork !== null && forkText.version === undefined ? (
          <Skeleton className="min-h-[22rem] w-full" />
        ) : (
          <SkillWorkbench
            key={`${skill.id}:${forkVersionId ?? "main"}`}
            skill={shown}
            fork={fork !== null}
            canEdit={skill.can_edit === true}
            isSaving={edit.isPending || save.isPending}
            categorySuggestions={categorySuggestions(categories, suggestedCategories)}
            saveWarning={
              fork === null
                ? t("warnMain", { number: next, count: followers })
                : t("warnFork", { number: next, name: fork.name, count: followers })
            }
            onSave={(change) => void handleSave(change)}
            onCancel={onClose}
            onDelete={onDelete}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
