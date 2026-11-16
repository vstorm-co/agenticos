"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { categorySuggestions } from "@/components/skills/category-input";
import { SaveConfirmDialog } from "@/components/skills/save-confirm-dialog";
import { SkillCheckDialog } from "@/components/skills/skill-check-dialog";
import { SkillWorkbench } from "@/components/skills/skill-workbench";
import { EditorLoading } from "@/components/files/editor-loading";
import { ErrorState } from "@/components/states";
import { SkillEditorFrame, leaveSkillEditor } from "./skill-editor-frame";
import { useSkill, useSkills } from "@/hooks";
import { useSkillVersion, useSkillVersionWrites } from "@/hooks/use-skill-versions";
import type { SkillEdit } from "@/hooks/use-skills";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import type { Skill } from "@/types/providers";
import type { SkillFork } from "@/types/skill-versions";

type SkillEditorProps = Omit<Parameters<typeof EditSkillDialogBody>[0], "onBusyChange">;

export function EditSkillDialog(props: SkillEditorProps) {
  const [busy, setBusy] = useState(false);
  const t = useTranslations("skills.page.edit");
  return (
    <SkillEditorFrame
      id={props.skill.id}
      title={
        props.fork === null
          ? props.skill.name
          : t("forkTitle", { skill: props.skill.name, name: props.fork.name })
      }
      description={props.fork === null ? t("nameHowModelRefers") : t("forkFiles")}
      busy={busy}
      onClose={props.onClose}
    >
      <EditSkillDialogBody {...props} onBusyChange={setBusy} />
    </SkillEditorFrame>
  );
}

/**
 * The skill's editor, saving a new version on the line the page is showing.
 *
 * On main it is the whole skill; on a fork it is the fork's newest text, and only
 * that text - the files and the category are main's. The version a save is written
 * over is the one on screen when the dialog opened, or the one a file written here
 * made, so a line somebody else moved since is refused, and the text stays for the
 * person to keep. A text brought back from a check opens in place of the stored one.
 */
export function EditSkillDialogBody({
  skill,
  fork,
  followers,
  readers,
  canCheck,
  draft,
  onClose,
  onDelete,
  onOpenFull,
  onBusyChange,
}: {
  skill: Skill;
  fork: SkillFork | null;
  /** How many agents follow the line being edited, and so get the save at once. */
  followers: number;
  /** The followers the reader may see, by name. */
  readers: string[];
  /** Whether the reader may check a change on the line's agents before it goes live. */
  canCheck: boolean;
  /**
   * A checked text to go on editing, saved over the version it was checked on, so a
   * version saved since is refused rather than written over.
   */
  draft?: { description: string; content: string; baseVersionId: string };
  onClose: () => void;
  onDelete: () => void;
  onOpenFull?: () => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const t = useTranslations("skills.page.edit");
  const tSkills = useTranslations("skills");
  const tErrors = useTranslations("errors");
  const { categories, suggestedCategories } = useSkills({ limit: 1 });
  const { save } = useSkill(skill.id);
  const { edit } = useSkillVersionWrites(skill.id);
  useEffect(() => {
    onBusyChange(edit.isPending || save.isPending);
    return () => onBusyChange(false);
  }, [edit.isPending, save.isPending, onBusyChange]);
  const queryClient = useQueryClient();
  const [opened] = useState(
    () =>
      draft?.baseVersionId ??
      (fork === null ? skill.latest_version_id : (fork.latest?.id ?? fork.base.id)),
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
  // A text change waits here for the person to save it now or check it first.
  const [pending, setPending] = useState<SkillEdit | null>(null);
  const [checking, setChecking] = useState<{ change: SkillEdit; base: string } | null>(null);
  const version =
    fork === null
      ? t("version", { number: next })
      : t("forkVersion", { name: fork.name, number: next });
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

  const textChanged = (change: SkillEdit) =>
    change.description !== shown.description || change.content !== shown.content;

  async function saveCategory(change: SkillEdit) {
    // The category is the skill's, not a version's, so it is saved beside the text.
    if (fork === null && change.category !== skill.category) {
      await save.mutateAsync({ category: change.category });
    }
  }

  async function handleSave(change: SkillEdit, confirmed = false) {
    setRefusal(null);
    if (textChanged(change) && !confirmed) {
      setPending(change);
      return false;
    }
    setPending(null);
    try {
      if (textChanged(change)) {
        if (baseId === null) {
          setRefusal(t("noBase"));
          return false;
        }
        await edit.mutateAsync({
          forkId: fork?.id ?? null,
          baseVersionId: baseId,
          description: change.description,
          content: change.content,
        });
      }
      await saveCategory(change);
      toast.success(
        !textChanged(change)
          ? tSkills("savedAgentsCurrent")
          : fork === null
            ? t("saved", { number: next })
            : t("savedFork", { name: fork.name, number: next }),
      );
      onClose();
      return true;
    } catch (failure) {
      setRefusal(
        failure instanceof ApiError && failure.status === 409
          ? t("lineMoved")
          : getErrorMessage(failure, tErrors),
      );
      return false;
    }
  }

  const leaveEditor = (proceed: () => void) => {
    if (!edit.isPending && !save.isPending) leaveSkillEditor(skill.id, proceed);
  };

  const closeEditor = () => leaveEditor(onClose);
  return (
    <>
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
        <EditorLoading
          kind="skill"
          canEdit={skill.can_edit === true}
          files={false}
          fullView={onOpenFull !== undefined}
        />
      ) : (
        <SkillWorkbench
          key={`${skill.id}:${opened}`}
          skill={
            draft ? { ...shown, description: draft.description, content: draft.content } : shown
          }
          fork={fork !== null}
          canEdit={skill.can_edit === true}
          isSaving={edit.isPending || save.isPending}
          categorySuggestions={categorySuggestions(categories, suggestedCategories)}
          saveWarning={
            fork === null
              ? t("warnMain", { number: next, count: followers })
              : t("warnFork", { number: next, name: fork.name, count: followers })
          }
          onSave={(change) => handleSave(change)}
          onFilesWritten={followFiles}
          onCancel={closeEditor}
          onOpenFull={onOpenFull ? () => leaveEditor(onOpenFull) : undefined}
          onDelete={fork === null ? onDelete : undefined}
        />
      )}
      {pending !== null && (
        <SaveConfirmDialog
          version={version}
          reach={followers}
          readers={readers}
          canCheck={canCheck}
          onCheck={() => {
            setPending(null);
            if (baseId === null) setRefusal(t("noBase"));
            else setChecking({ change: pending, base: baseId });
          }}
          onSave={() => void handleSave(pending, true)}
          onCancel={() => setPending(null)}
        />
      )}
      {checking !== null && (
        <SkillCheckDialog
          skillId={skill.id}
          change={{
            candidate: {
              description: checking.change.description,
              content: checking.change.content,
            },
            baseVersionId: checking.base,
          }}
          forkId={fork?.id ?? null}
          onOpenChange={(open) => !open && setChecking(null)}
          onEdit={() => setChecking(null)}
          onApplied={() => {
            void saveCategory(checking.change).then(onClose, (failure: unknown) =>
              setRefusal(getErrorMessage(failure, tErrors)),
            );
          }}
          onLineMoved={() => {
            setChecking(null);
            setRefusal(t("lineMoved"));
            void queryClient.invalidateQueries({ queryKey: qk.skills.all() });
          }}
        />
      )}
    </>
  );
}
