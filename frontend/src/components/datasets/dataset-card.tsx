"use client";

import Link from "next/link";
import { Building2, FlaskConical, Lock, Puzzle, Trash2, Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { DatasetChip, DatasetIcon } from "./dataset-chip";
import { datasetNextStep } from "./dataset-journey";
import { timeAgo } from "@/lib/utils";
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
  const tt = useTranslations("time");
  const locale = useLocale();
  const VisibilityIcon = VISIBILITY_ICON[dataset.visibility];
  const next = datasetNextStep(dataset);
  const edited = dataset.updated_at ?? dataset.created_at;

  return (
    <div className="h-full">
      <div className="border-foreground/8 bg-card hover:border-foreground/25 relative flex h-full flex-col gap-3 rounded-xl border p-4 transition-colors">
        <Link
          href={ROUTES.DATASET_DETAIL(dataset.id)}
          data-tour="dataset-card-open"
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: dataset.name })}
        />
        <div className="pointer-events-none relative flex items-start gap-3">
          <DatasetIcon tone="gray" icon={FlaskConical} className="size-10" />
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <p className="text-foreground truncate font-medium">{dataset.name}</p>
              {dataset.latest_version > 0 && (
                <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
                  {t("versionNumber", { number: dataset.latest_version })}
                </Badge>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <span className="text-muted-foreground text-xs">
                {t("caseCount", { count: dataset.case_count })}
              </span>
              <DatasetChip tone="gray">{t(`journey.status.${next}`)}</DatasetChip>
            </div>
            <p className="text-muted-foreground mt-2 line-clamp-2 min-h-10 text-sm">
              {dataset.description}
            </p>
          </div>
        </div>
        <div className="text-muted-foreground relative mt-auto flex min-w-0 flex-wrap items-center gap-2 pt-3 text-xs">
          <span
            role="img"
            aria-label={t(`visibility.${dataset.visibility}`)}
            title={t(`visibility.${dataset.visibility}`)}
            className="pointer-events-none inline-flex items-center gap-1"
          >
            <VisibilityIcon className="h-3.5 w-3.5" aria-hidden />
            <span>{t(`visibility.${dataset.visibility}`)}</span>
          </span>
          <span className="pointer-events-none min-w-0 flex-1 break-words">
            {t("editedWhen", { when: timeAgo(edited, tt, locale) })}
          </span>
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
      </div>
    </div>
  );
}
