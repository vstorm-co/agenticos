"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import { useSkillMerge } from "@/hooks/use-skill-merge";
import { getErrorMessage } from "@/lib/api-error";
import { standing } from "@/lib/improvement-steps";
import type { SkillImprovement } from "@/types/skill-improvement";
import { MergeFiles } from "./merge-files";
import { MergeText } from "./merge-text";

/**
 * Changes for a catch-up or a move to main: the merge of the fork's base, the fork and
 * main, part by part. What one side changed is taken as it is; a conflict the assistant
 * could not write a text for is marked, and the check waits until nothing is left open.
 */
export function MergeChanges({
  session,
  editable,
}: {
  session: SkillImprovement;
  editable: boolean;
}) {
  const t = useTranslations("skillImprovement.merge");
  const tErrors = useTranslations("errors");
  const tImprovement = useTranslations("improvement");
  const actions = useSkillMerge(session.skill_id, session.id, { at: standing(session) });
  const [refusal, setRefusal] = useState<string | null>(null);
  const { merge } = actions;
  if (actions.isLoading) return <LoadingState variant="pending" />;
  if (actions.error || !merge)
    return (
      <ErrorState
        description={getErrorMessage(actions.error, tErrors)}
        cta={{ label: tImprovement("retryRead"), onClick: () => void actions.refetch() }}
      />
    );
  async function save(write: () => Promise<unknown>): Promise<boolean> {
    setRefusal(null);
    try {
      await write();
      return true;
    } catch (failure) {
      setRefusal(getErrorMessage(failure, tErrors));
      return false;
    }
  }
  const leftForYou = [merge.description, ...merge.parts].filter(
    (text) => text.state === "conflict" && text.result === null && text.proposed === null,
  ).length;
  return (
    <section className="space-y-4" data-tour="skill-merge-changes">
      <p className="text-sm">
        {t(`sides.${merge.kind}`, {
          line: session.line_name,
          base: merge.base.number,
          fork: merge.fork.number,
          main: merge.main.number,
        })}
      </p>
      {merge.unresolved > 0 ? (
        <div role="alert" className="text-destructive space-y-1 text-sm">
          <p className="font-medium">{t("unresolved", { count: merge.unresolved })}</p>
          {leftForYou > 0 && <p>{t("leftForYou", { count: leftForYou })}</p>}
        </div>
      ) : (
        <p role="status" className="text-sm">
          {t("settledAll", { conflicts: merge.conflicts })}
        </p>
      )}
      {merge.description.state === "same" ? (
        <p className="text-muted-foreground text-xs">{t("descriptionSame")}</p>
      ) : (
        <MergeText
          label={t("description")}
          text={merge.description}
          editable={editable}
          saving={actions.editDescription.isPending}
          maxLength={DESCRIPTION_CHARS}
          onSave={(result) => save(() => actions.editDescription.mutateAsync(result))}
        />
      )}
      {merge.parts.map((part, index) =>
        part.state === "same" ? (
          <details key={index} className="text-muted-foreground text-xs">
            <summary className="cursor-pointer">
              {t("unchangedLines", { count: lines(part.base) })}
            </summary>
            <pre className="mt-1 font-mono break-words whitespace-pre-wrap">{part.base}</pre>
          </details>
        ) : (
          <MergeText
            key={index}
            label={t("part", { number: index + 1 })}
            text={part}
            editable={editable}
            saving={actions.editPart.isPending}
            onSave={(result) => save(() => actions.editPart.mutateAsync({ index, result }))}
          />
        ),
      )}
      <MergeFiles
        files={merge.files}
        editable={editable}
        saving={actions.pickFile.isPending}
        onPick={(name, take) => void save(() => actions.pickFile.mutateAsync({ name, take }))}
      />
      {refusal !== null && (
        <p role="alert" className="text-destructive text-sm">
          {refusal}
        </p>
      )}
    </section>
  );
}

/** As long as a skill's description may be. */
const DESCRIPTION_CHARS = 500;

/** How many lines a part holds; a part ends on its line break. */
function lines(text: string): number {
  return text.split("\n").length - (text.endsWith("\n") ? 1 : 0);
}
