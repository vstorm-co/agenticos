"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { AddFromMessage } from "@/hooks/use-datasets";
import { ROUTES } from "@/lib/constants";
import type { Dataset } from "@/types/datasets";

export type AnswerAs = AddFromMessage["answerAs"];

interface DatasetTargetFieldsProps {
  /** The datasets the caller may add to; empty once loaded means there is none. */
  editable: Dataset[];
  isLoading: boolean;
  datasetId: string;
  onDatasetChange: (id: string) => void;
  answerAs: AnswerAs;
  onAnswerAsChange: (next: AnswerAs) => void;
  /** Keeps two of these on one page from sharing input ids. */
  idPrefix: string;
}

/**
 * Which dataset an answer goes into, and whether it is kept as the bad answer or the good one.
 *
 * Shared by "Add to dataset" in Activity and the rate-down dialog in chat, so the
 * two ask the same two questions in the same words.
 */
export function DatasetTargetFields({
  editable,
  isLoading,
  datasetId,
  onDatasetChange,
  answerAs,
  onAnswerAsChange,
  idPrefix,
}: DatasetTargetFieldsProps) {
  const t = useTranslations("datasets");
  if (!isLoading && editable.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        {t.rich("noDatasetToAddTo", {
          link: (chunks) => (
            <Link href={ROUTES.DATASETS} className="underline">
              {chunks}
            </Link>
          ),
        })}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <FormField htmlFor={`${idPrefix}-dataset`} label={t("dataset")}>
        <Select value={datasetId} onValueChange={onDatasetChange}>
          <SelectTrigger id={`${idPrefix}-dataset`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {editable.map((dataset) => (
              <SelectItem key={dataset.id} value={dataset.id}>
                {dataset.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      <FormField htmlFor={`${idPrefix}-answer-as`} label={t("keepAnswerAs")}>
        <Select value={answerAs} onValueChange={(next) => onAnswerAsChange(next as AnswerAs)}>
          <SelectTrigger id={`${idPrefix}-answer-as`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="counter_example">{t("field.counter_example")}</SelectItem>
            <SelectItem value="reference_answer">{t("field.reference_answer")}</SelectItem>
          </SelectContent>
        </Select>
      </FormField>
    </div>
  );
}
