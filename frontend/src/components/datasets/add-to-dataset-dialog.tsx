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
}

/**
 * Which dataset an answer goes into.
 *
 * The question, the turns before it and the rating's comment come with it on the
 * server; this asks only what the server cannot know.
 */
export function AddToDatasetDialog({
  open,
  onOpenChange,
  messageId,
  answerAs: initial,
  askAnswerAs,
  ratedDown = false,
}: AddToDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const { editable, isLoading, search, target, returnTo, choose, remember, create } =
    useDatasetTarget();
  const add = useAddToDataset();
  const [answerAs, setAnswerAs] = useState<AnswerAs>(initial);
  const [newName, setNewName] = useState(t("newDatasetFromActivity"));
  // With nothing to add to, somebody who may create a dataset makes one here.
  const making = !isLoading && editable.length === 0 && can(Perm.datasetsEdit);

  async function submit() {
    try {
      const into =
        target ??
        (await create.mutateAsync({ name: newName.trim(), description: null, visibility: "org" }));
      await add.mutateAsync({ datasetId: into.id, messageId, answerAs });
      remember(into);
      const added = t("addedTo", { name: into.name });
      if (returnTo === undefined) toast.success(added);
      else
        toast.success(added, {
          action: {
            label: t("backToDataset", { name: returnTo.name }),
            onClick: () => router.push(`${ROUTES.DATASET_DETAIL(returnTo.id)}?tab=cases`),
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
