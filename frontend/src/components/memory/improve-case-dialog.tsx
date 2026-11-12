"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  FormField,
  Textarea,
} from "@/components/ui";
import { DatasetTargetFields } from "@/components/datasets/dataset-target-fields";
import { useDatasetTarget } from "@/components/datasets/use-dataset-target";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { reviewDecisionCase, type DecisionEpisode, type MemoryClaim } from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";

/**
 * The reviewed text of one decision episode, added as a case to a dataset the person
 * may edit. Mounted only while open, so the page around it reads no datasets.
 */
export function ImproveCaseDialog({
  claim,
  episode,
  onClose,
}: {
  claim: MemoryClaim;
  episode: DecisionEpisode;
  onClose: () => void;
}) {
  const formId = useId();
  const t = useTranslations("pages.memory.claims.episode");
  const td = useTranslations("datasets");
  const errors = useTranslations("errors");
  const tc = useTranslations("common");
  const router = useRouter();
  const queryClient = useQueryClient();
  const { editable, isLoading, error, refetch, search, target, choose, remember } =
    useDatasetTarget();
  // Consent names the dataset it was given for: one resolved or chosen later voids it.
  const [consentedTo, setConsentedTo] = useState<string | null>(null);
  const confirmed = target !== undefined && consentedTo === target.id;
  const [input, setInput] = useState(episode.situation);
  const [reference, setReference] = useState(episode.correction ?? episode.choice);
  const add = useMutation({
    mutationFn: (into: Dataset) =>
      reviewDecisionCase(claim.id, into.id, input.trim(), reference.trim()),
    onSuccess: (_, into) => {
      remember(into);
      void queryClient.invalidateQueries({ queryKey: qk.datasets.all() });
      toast.success(td("addedTo", { name: into.name }), {
        action: {
          label: td("openDataset"),
          onClick: () => router.push(`${ROUTES.DATASET_DETAIL(into.id)}?tab=cases`),
        },
      });
      onClose();
    },
  });
  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next && !add.isPending) onClose();
      }}
    >
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("export")}</DialogTitle>
          <DialogDescription>{t("review")}</DialogDescription>
        </DialogHeader>
        <div className={cn(DIALOG_BODY, "space-y-5")}>
          {error ? (
            <div role="alert" className="space-y-2 text-sm">
              <p className="text-destructive-ink">{getErrorMessage(error, errors)}</p>
              <Button variant="outline" size="sm" onClick={() => void refetch()}>
                {tc("retry")}
              </Button>
            </div>
          ) : (
            <DatasetTargetFields
              editable={editable}
              isLoading={isLoading}
              datasetId={target?.id ?? ""}
              onDatasetChange={(id) => {
                choose(id);
                setConsentedTo(null);
              }}
              search={search}
              idPrefix={formId}
            />
          )}
          <FormField htmlFor={`${formId}-input`} label={t("input")}>
            <Textarea
              id={`${formId}-input`}
              maxLength={32000}
              aria-label={t("input")}
              value={input}
              onChange={(event) => {
                setInput(event.target.value);
                setConsentedTo(null);
              }}
            />
          </FormField>
          <FormField htmlFor={`${formId}-reference`} label={t("reference")}>
            <Textarea
              id={`${formId}-reference`}
              maxLength={32000}
              aria-label={t("reference")}
              value={reference}
              onChange={(event) => {
                setReference(event.target.value);
                setConsentedTo(null);
              }}
            />
          </FormField>
          <label className="flex items-center gap-2 text-sm">
            <Checkbox
              checked={confirmed}
              disabled={target === undefined}
              onCheckedChange={(value) => setConsentedTo(value === true ? target!.id : null)}
            />
            {t("consent")}
          </label>
          {add.error ? <p role="alert">{getErrorMessage(add.error, errors)}</p> : null}
          <Button
            disabled={
              target === undefined ||
              !confirmed ||
              !input.trim() ||
              !reference.trim() ||
              add.isPending
            }
            onClick={() => target !== undefined && add.mutate(target)}
          >
            {t("add")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
