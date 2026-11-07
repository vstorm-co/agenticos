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
import { useAddToDataset, useDatasetSource } from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { Perm } from "@/types/permissions";
import { DatasetTargetFields, type AnswerAs } from "./dataset-target-fields";
import { asksAboutHistory, type AskedBefore } from "./follows-on";
import { DatasetSourcePreview } from "./dataset-source-preview";
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
   * The question, when the surface showing the answer knows it: one that plainly
   * follows on is pointed out, and one with nothing before it is not asked about.
   * Either way the question alone is what is chosen until the reader picks more.
   */
  asked?: AskedBefore;
  /** Already visible in Activity; no additional transcript is fetched. */
  answer?: string;
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
  answer,
}: AddToDatasetDialogProps) {
  const t = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const router = useRouter();
  const { can } = usePermissions();
  const {
    editable,
    isLoading,
    error: listingError,
    refetch,
    search,
    target: listedTarget,
    returnTo,
    choose,
    remember,
    create,
  } = useDatasetTarget();
  const add = useAddToDataset();
  const source = useDatasetSource(messageId, open);
  const [answerAs, setAnswerAs] = useState<AnswerAs>(initial);
  const [withHistory, setWithHistory] = useState(false);
  const [newName, setNewName] = useState(t("newDatasetFromActivity"));
  // Retain a successful create if the subsequent add fails, so retrying never
  // creates a second dataset while the listing is catching up.
  const [created, setCreated] = useState<Dataset | null>(null);
  const target = created ?? listedTarget;
  const making =
    !listingError &&
    !isLoading &&
    !search?.value &&
    editable.length === 0 &&
    target === undefined &&
    can(Perm.datasetsEdit);
  const busy = add.isPending || create.isPending;
  const [failure, setFailure] = useState<string | null>(null);

  async function submit() {
    setFailure(null);
    try {
      let into = target;
      if (into === undefined) {
        into = await create.mutateAsync({
          name: newName.trim(),
          description: null,
          visibility: "org",
        });
        setCreated(into);
        choose(into.id);
      }
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
      setFailure(getErrorMessage(error, tErrors));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
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
        <div className={cn(DIALOG_BODY, "space-y-5")}>
          {listingError && (
            <div role="alert" className="space-y-2 text-sm">
              <p className="text-destructive-ink">{getErrorMessage(listingError, tErrors)}</p>
              <Button variant="outline" size="sm" onClick={() => void refetch()}>
                {tc("retry")}
              </Button>
            </div>
          )}
          {source.data?.private_to_other && (
            <p role="note" className="rounded-md border p-3 text-sm">
              {t("privateConversationWarning", {
                name: source.data.owner_name ?? t("anotherMember"),
              })}
            </p>
          )}
          {source.isLoading && (
            <p className="text-muted-foreground text-sm">{t("checkingSource")}</p>
          )}
          {source.error && (
            <p role="alert" className="text-destructive-ink text-sm">
              {getErrorMessage(source.error, tErrors)}
            </p>
          )}
          {!listingError && (
            <DatasetTargetFields
              editable={
                created && !editable.some((item) => item.id === created.id)
                  ? [created, ...editable]
                  : editable
              }
              isLoading={isLoading}
              datasetId={target?.id ?? ""}
              onDatasetChange={(id) => {
                setCreated(null);
                choose(id);
              }}
              search={search}
              answerAs={askAnswerAs ? { value: answerAs, onChange: setAnswerAs } : undefined}
              idPrefix="add-to-dataset"
              create={making ? { name: newName, onChange: setNewName } : undefined}
            />
          )}
          {asksAboutHistory(asked) && (
            <HistoryChoice
              idPrefix="add-to-dataset"
              withHistory={withHistory}
              onChange={setWithHistory}
              asked={asked}
            />
          )}
          {asked && answer !== undefined && (
            <DatasetSourcePreview question={asked.question} answer={answer} />
          )}
          {failure && (
            <p role="alert" className="text-destructive-ink text-sm">
              {failure}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            loading={busy}
            disabled={
              Boolean(listingError) ||
              source.data === undefined ||
              source.error !== null ||
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
