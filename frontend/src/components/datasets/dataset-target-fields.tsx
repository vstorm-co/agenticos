"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import {
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { AddFromMessage } from "@/hooks/use-datasets";
import { SearchInput } from "@/components/ui/list-controls";
import { AnswerPurpose } from "./answer-purpose";
import { ROUTES } from "@/lib/constants";
import type { Dataset } from "@/types/datasets";

export type AnswerAs = AddFromMessage["answerAs"];

interface DatasetTargetFieldsProps {
  /** The datasets the caller may add to; empty once loaded means there is none. */
  editable: Dataset[];
  isLoading: boolean;
  datasetId: string;
  onDatasetChange: (id: string) => void;
  /**
   * Asked only where the answer could be either: in Activity. In chat the rating
   * already said which, so the question is not shown.
   */
  answerAs?: { value: AnswerAs; onChange: (next: AnswerAs) => void };
  /** A search over every dataset, offered once the listing stops short of them all. */
  search?: { value: string; onChange: (value: string) => void } | null;
  /** Keeps two of these on one page from sharing input ids. */
  idPrefix: string;
  /** With no dataset to add to, the name of one to create; absent, a link to Datasets. */
  create?: { name: string; onChange: (name: string) => void };
}

/**
 * Which dataset an answer goes into and, where it is asked, whether it is kept as
 * the bad answer or the good one. Shared by every way an answer is added, so they
 * ask in the same words.
 */
export function DatasetTargetFields({
  editable,
  isLoading,
  datasetId,
  onDatasetChange,
  answerAs,
  search,
  idPrefix,
  create,
}: DatasetTargetFieldsProps) {
  const t = useTranslations("datasets");
  const finder = search && (
    <SearchInput
      value={search.value}
      onChange={search.onChange}
      placeholder={t("findDataset")}
      className="sm:w-full"
    />
  );
  const none = !isLoading && editable.length === 0 && !search?.value;
  if (none && !create) {
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
      {finder}
      {!isLoading && editable.length === 0 && search?.value && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("noMatchingDatasets")}
        </p>
      )}
      {none && create ? (
        <FormField
          htmlFor={`${idPrefix}-new-dataset`}
          label={t("newDatasetName")}
          description={t("newDatasetHere")}
        >
          <Input
            id={`${idPrefix}-new-dataset`}
            value={create.name}
            maxLength={120}
            onChange={(event) => create.onChange(event.target.value)}
          />
        </FormField>
      ) : (
        <FormField htmlFor={`${idPrefix}-dataset`} label={t("dataset")}>
          <Select
            value={datasetId}
            onValueChange={onDatasetChange}
            disabled={isLoading || editable.length === 0}
          >
            <SelectTrigger id={`${idPrefix}-dataset`}>
              <SelectValue placeholder={isLoading ? t("loadingDatasets") : t("chooseDataset")} />
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
      )}
      {answerAs && <AnswerPurpose value={answerAs.value} onChange={answerAs.onChange} />}
    </div>
  );
}
