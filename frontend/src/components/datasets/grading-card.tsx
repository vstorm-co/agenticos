"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import type { LucideIcon } from "lucide-react";
import { DatasetIcon } from "./dataset-chip";
import type { DatasetTone } from "./dataset-chip";
import { Badge } from "@/components/ui";

interface GradingCardProps {
  title: string;
  icon: LucideIcon;
  tone: DatasetTone;
  description: string;
  /** Whether this card holds a change not yet saved, which the tab's save bar saves. */
  dirty: boolean;
  tour?: string;
  children: ReactNode;
}

/** One part of a dataset's grading, marked while it holds a change not yet saved. */
export function GradingCard({
  title,
  description,
  dirty,
  tour,
  children,
  icon: Icon,
  tone,
}: GradingCardProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <section className="bg-card flex h-full min-w-0 flex-col overflow-hidden rounded-xl border">
      <header className="flex items-start gap-3 border-b p-4 sm:p-5 xl:min-h-28">
        <DatasetIcon tone={tone} icon={Icon} className="size-9" />
        <div className="min-w-0 flex-1 space-y-1">
          <h2 className="text-sm font-semibold">{title}</h2>
          <p className="text-muted-foreground text-xs leading-relaxed">{description}</p>
        </div>
        {dirty && (
          <Badge variant="outline" className="font-normal">
            {t("unsaved")}
          </Badge>
        )}
      </header>
      <div className="flex-1 space-y-4 p-4 sm:p-5" data-tour={tour}>
        {children}
      </div>
    </section>
  );
}
