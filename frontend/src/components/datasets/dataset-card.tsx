"use client";

import Link from "next/link";
import { useState } from "react";
import { Building2, FlaskConical, Lock, Trash2, Users } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { Beam } from "@/components/ui/beam";
import { ROUTES } from "@/lib/constants";
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
  const [hovered, setHovered] = useState(false);
  const VisibilityIcon = VISIBILITY_ICON[dataset.visibility];
  const edited = dataset.updated_at ?? dataset.created_at;

  return (
    <Beam
      size="md"
      borderRadius={12}
      active={hovered}
      onHoverChange={setHovered}
      className="h-full rounded-xl"
    >
      <div className="border-border bg-card hover:border-foreground/25 relative flex h-full flex-col gap-3 rounded-xl border p-4 transition-colors">
        <Link
          href={ROUTES.DATASET_DETAIL(dataset.id)}
          data-tour="dataset-card-open"
          className="focus-visible:ring-ring absolute inset-0 rounded-xl outline-none focus-visible:ring-2"
          aria-label={tc("openNamed", { name: dataset.name })}
        />
        <div className="pointer-events-none relative flex items-start gap-3">
          <span className="bg-foreground/[0.04] text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-lg">
            <FlaskConical aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <p className="text-foreground truncate font-medium">{dataset.name}</p>
              {dataset.latest_version > 0 && (
                <Badge variant="outline" className="text-muted-foreground shrink-0 font-normal">
                  {t("versionNumber", { number: dataset.latest_version })}
                </Badge>
              )}
            </div>
            <p className="text-muted-foreground text-xs">
              {t("caseCount", { count: dataset.case_count })}
            </p>
            <p className="text-muted-foreground mt-2 line-clamp-2 min-h-10 text-sm">
              {dataset.description}
            </p>
          </div>
        </div>
        <div className="text-muted-foreground relative mt-auto flex items-center gap-2 border-t pt-3 text-xs">
          <span
            role="img"
            aria-label={t(`visibility.${dataset.visibility}`)}
            title={t(`visibility.${dataset.visibility}`)}
            className="pointer-events-none inline-flex items-center gap-1"
          >
            <VisibilityIcon className="h-3.5 w-3.5" aria-hidden />
            <span>{t(`visibility.${dataset.visibility}`)}</span>
          </span>
          <span className="pointer-events-none">
            {t("editedWhen", { when: timeAgo(edited, tt, locale) })}
          </span>
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
    </Beam>
  );
}
