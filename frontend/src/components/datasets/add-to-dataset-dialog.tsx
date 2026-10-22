"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAddToDataset } from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { Perm } from "@/types/permissions";
import { DatasetTargetFields, type AnswerAs } from "./dataset-target-fields";
import { asksAboutHistory, keepsHistoryFirst, type AskedBefore } from "./follows-on";
import { HistoryChoice } from "./history-choice";
import { useDatasetTarget } from "./use-dataset-target";

interface AddToDatasetDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The agent's answer that becomes the case. */
  messageId: string;
  /** What the answer is kept as, or what is offered first when `askAnswerAs`. */
  answerAs: AnswerAs;
  /**
   * Whether the reader picks it. True in Activity, where a turn may carry no
   * rating; false after a thumbs-up in chat, where the rating already said.
   */
  askAnswerAs: boolean;
  /** Whether the answer was rated down, so the rating's comment comes with it. */
  ratedDown?: boolean;
  /**
   * The question, when the surface showing the answer knows it. It picks whether
   * the conversation before it is kept by default; a question with nothing before
   * it is not asked about. Unknown, the reader chooses and the question alone is
   * offered first.
   */
  asked?: AskedBefore;
}

/**
 * Which dataset an answer goes into.
 *
 * The question and the rating's comment come with it on the server; this asks
 * only what the server cannot know - where to, and whether the turns before the
 * question come too.
 */
export function AddToDatasetDialog({
  open,
  onOpenChange,
  messageId,
  answerAs: initial,
  askAnswerAs,
  ratedDown = false,
  asked,
}: AddToDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const { editable, isLoading, search, target, returnTo, choose, remember, create } =
    useDatasetTarget();
  const add = useAddToDataset();
  const [answerAs, setAnswerAs] = useState<AnswerAs>(initial);
  const [withHistory, setWithHistory] = useState(keepsHistoryFirst(asked));
  const [newName, setNewName] = useState(t("newDatasetFromActivity"));
  const making = !isLoading && editable.length === 0 && can(Perm.datasetsEdit);

  async function submit() {
    try {
      const into =
        target ??
        (await create.mutateAsync({ name: newName.trim(), description: null, visibility: "org" }));
      await add.mutateAsync({ datasetId: into.id, messageId, answerAs, withHistory });
      remember(into);
      const back = returnTo ?? into;
      toast.success(t("addedTo", { name: into.name }), {
        action: {
          label:
            returnTo === undefined ? t("openDataset") : t("backToDataset", { name: returnTo.name }),
          onClick: () => router.push(`${ROUTES.DATASET_DETAIL(back.id)}?tab=cases`),
        },
      });
      onOpenChange(false);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("addToDataset")}</DialogTitle>
          <DialogDescription>
            {t(
              !askAnswerAs
                ? "addAsReferenceBody"
                : ratedDown
                  ? "addToDatasetBody"
                  : "addToDatasetBodyPlain",
            )}
          </DialogDescription>
        </DialogHeader>
        <DatasetTargetFields
          editable={editable}
          isLoading={isLoading}
          datasetId={target?.id ?? ""}
          onDatasetChange={choose}
          search={search}
          answerAs={askAnswerAs ? { value: answerAs, onChange: setAnswerAs } : undefined}
          idPrefix="add-to-dataset"
          create={making ? { name: newName, onChange: setNewName } : undefined}
        />
        {asksAboutHistory(asked) && (
          <HistoryChoice
            idPrefix="add-to-dataset"
            withHistory={withHistory}
            onChange={setWithHistory}
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={
              add.isPending ||
              create.isPending ||
              (target === undefined && !(making && newName.trim() !== ""))
            }
            onClick={() => void submit()}
          >
            {t("add")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
