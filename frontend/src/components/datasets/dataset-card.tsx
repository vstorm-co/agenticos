"use client";

import Link from "next/link";
import { FlaskConical, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Badge, Button, Card } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { Dataset } from "@/types/datasets";

interface DatasetCardProps {
  dataset: Dataset;
  onDelete: () => void;
}

/** One dataset in the list: what it is for, how many cases, and at which version. */
export function DatasetCard({ dataset, onDelete }: DatasetCardProps) {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  return (
    <Card className="group hover:border-foreground/20 relative h-full">
      <Link href={`${ROUTES.DATASETS}/${dataset.id}`} className="flex h-full flex-col gap-1.5 p-4">
        <span className="flex items-center gap-2 pr-8">
          <FlaskConical className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
          <span className="text-foreground truncate text-sm font-medium">{dataset.name}</span>
          {dataset.latest_version > 0 && (
            <Badge variant="outline">
              {t("versionNumber", { number: dataset.latest_version })}
            </Badge>
          )}
        </span>
        {dataset.description !== null && (
          <span className="text-muted-foreground line-clamp-2 block text-sm">
            {dataset.description}
          </span>
        )}
        <span className="text-muted-foreground mt-auto pt-1 text-xs">
          {t("caseCount", { count: dataset.case_count })}
        </span>
      </Link>
      {dataset.can_edit && (
        <Button
          variant="ghost"
          size="icon"
          aria-label={tc("deleteNamed", { name: dataset.name })}
          onClick={onDelete}
          className="hover-reveal absolute right-2 bottom-2"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      )}
    </Card>
  );
}
