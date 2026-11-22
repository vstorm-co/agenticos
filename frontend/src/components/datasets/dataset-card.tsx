"use client";

import Link from "next/link";
import { Building2, FlaskConical, Lock, Puzzle, Trash2, Users } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  ResourceCard,
  ResourceCardHeader,
  ResourceCardDescription,
  ResourceCardFooter,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { DatasetIcon } from "./dataset-chip";
import { datasetNextStep } from "./dataset-journey";
import type { Dataset } from "@/types/datasets";

const VISIBILITY_ICON = { org: Building2, team: Users, private: Lock } as const;

interface DatasetCardProps {
  dataset: Dataset;
  onDelete: () => void;
}

/**
 * One dataset in the list - the agents gallery's card, for a dataset: what it is
 * called, how many cases it holds and at which version, who may reach it and when
 * it last changed.
 */
export function DatasetCard({ dataset, onDelete }: DatasetCardProps) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const VisibilityIcon = VISIBILITY_ICON[dataset.visibility];
  const next = datasetNextStep(dataset);

  return (
    <ResourceCard className="min-h-52">
      <Link
        href={ROUTES.DATASET_DETAIL(dataset.id)}
        data-tour="dataset-card-open"
        className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
        aria-label={tc("openNamed", { name: dataset.name })}
      />
      <ResourceCardHeader className="pointer-events-none">
        <DatasetIcon tone="gray" icon={FlaskConical} className="size-10" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-foreground line-clamp-2 font-semibold break-words">{dataset.name}</p>
          <span
            role="img"
            aria-label={t(`visibility.${dataset.visibility}`)}
            title={t(`visibility.${dataset.visibility}`)}
            className="text-muted-foreground flex items-center gap-1.5 text-xs"
          >
            <VisibilityIcon className="size-3 shrink-0" aria-hidden />
            <span>{t(`visibility.${dataset.visibility}`)}</span>
          </span>
        </div>
      </ResourceCardHeader>
      <ResourceCardDescription className="pointer-events-none my-4 line-clamp-2">
        {dataset.description}
      </ResourceCardDescription>
      <ResourceCardFooter className="pointer-events-none border-0 pt-0 text-xs">
        <span className="text-muted-foreground">
          {t("caseCount", { count: dataset.case_count })}
        </span>
        <span className="text-muted-foreground">{t(`journey.status.${next}`)}</span>
        {dataset.latest_version > 0 && (
          <span className="text-muted-foreground">
            {t("versionNumber", { number: dataset.latest_version })}
          </span>
        )}
      </ResourceCardFooter>
      <div className="text-muted-foreground relative mt-auto flex min-w-0 flex-wrap items-center gap-2 pt-3 text-xs">
        {dataset.skill_id && (
          <Link
            href={`${ROUTES.SKILL_DETAIL(dataset.skill_id)}#test-questions`}
            className="hover:text-foreground relative inline-flex items-center gap-1 underline-offset-4 hover:underline"
          >
            <Puzzle className="h-3.5 w-3.5" aria-hidden />
            {t("skillTestSet")}
          </Link>
        )}
        {dataset.can_edit && (
          <Button
            variant="ghost"
            size="icon"
            aria-label={tc("deleteNamed", { name: dataset.name })}
            onClick={onDelete}
            className="hover-reveal -my-1.5 ml-auto"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        )}
      </div>
    </ResourceCard>
  );
}
