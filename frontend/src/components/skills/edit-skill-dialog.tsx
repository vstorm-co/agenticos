"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { categorySuggestions } from "@/components/skills/category-input";
import { SkillWorkbench } from "@/components/skills/skill-workbench";
import { ErrorState } from "@/components/states";
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
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";
import { qk } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/providers";
import type { SkillFork } from "@/types/skill-versions";

/**
 * The skill's editor, saving a new version on the line the page is showing.
 *
 * On main it is the whole skill; on a fork it is the fork's newest text, and only
 * that text - the files and the category are main's. The version a save is written
 * over is the one on screen when the dialog opened, or the one a file written here
 * made, so a line somebody else moved since is refused, and the text stays for the
 * person to keep.
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
  const tSkills = useTranslations("skills");
  const tErrors = useTranslations("errors");
  const { categories, suggestedCategories } = useSkills({ limit: 1 });
  const { save } = useSkill(skill.id);
  const { edit } = useSkillVersionWrites(skill.id);
  const queryClient = useQueryClient();
  const [opened] = useState(() =>
    fork === null ? skill.latest_version_id : (fork.latest?.id ?? fork.base.id),
  );
  const [baseId, setBaseId] = useState(opened);
  const [next, setNext] = useState(() =>
    fork === null ? skill.version + 1 : (fork.latest?.number ?? 0) + 1,
  );
  // Files are main's: each write here is a new main version, read back once it settled.
  const followFiles = () => {
    const written = queryClient.getQueryData<Skill>(qk.skills.detail(skill.id));
    if (!written) return;
    setBaseId(written.latest_version_id);
    setNext(written.version + 1);
  };
  const [refusal, setRefusal] = useState<string | null>(null);
  const forkText = useSkillVersion(skill.id, fork === null ? null : opened);
  const shown =
    fork === null || forkText.version === undefined
      ? skill
      : {
          ...skill,
          description: forkText.version.description,
          content: forkText.version.content,
          resources: [],
        };

  async function handleSave(change: SkillEdit) {
    setRefusal(null);
    try {
      const textChanged =
        change.description !== shown.description || change.content !== shown.content;
      if (textChanged) {
        if (baseId === null) {
          setRefusal(t("noBase"));
          return;
        }
        await edit.mutateAsync({
          forkId: fork?.id ?? null,
          baseVersionId: baseId,
          description: change.description,
          content: change.content,
        });
      }
      // The category is the skill's, not a version's, so it is saved beside the text.
      if (fork === null && change.category !== skill.category) {
        await save.mutateAsync({ category: change.category });
      }
      toast.success(
        !textChanged
          ? tSkills("savedAgentsCurrent")
          : fork === null
            ? t("saved", { number: next })
            : t("savedFork", { name: fork.name, number: next }),
      );
      onClose();
    } catch (failure) {
      setRefusal(
        failure instanceof ApiError && failure.status === 409
          ? t("lineMoved")
          : getErrorMessage(failure, tErrors),
      );
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={cn(DIALOG_FILL, DIALOG_CANVAS, "max-md:overflow-y-auto")}>
        <DialogHeader>
          <DialogTitle className="font-mono">
            {fork === null ? skill.name : t("forkTitle", { skill: skill.name, name: fork.name })}
          </DialogTitle>
          <DialogDescription>
            {fork === null ? t("nameHowModelRefers") : t("forkFiles")}
          </DialogDescription>
        </DialogHeader>
        {refusal !== null && (
          <p role="alert" className="text-destructive text-sm">
            {refusal}
          </p>
        )}
        {fork !== null && forkText.error ? (
          <ErrorState
            description={getErrorMessage(forkText.error, tErrors)}
            cta={{ label: t("retryFork"), onClick: () => void forkText.refetch() }}
          />
        ) : fork !== null && forkText.version === undefined ? (
          <Skeleton className="min-h-[22rem] w-full" />
        ) : (
          <SkillWorkbench
            key={`${skill.id}:${opened}`}
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
            onFilesWritten={followFiles}
            onCancel={onClose}
            onDelete={fork === null ? onDelete : undefined}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
