"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { Badge } from "@/components/ui";

interface GradingCardProps {
  title: string;
  description: string;
  /** Whether this card holds a change not yet saved, which the tab's save bar saves. */
  dirty: boolean;
  tour?: string;
  children: ReactNode;
}

/** One part of a dataset's grading, marked while it holds a change not yet saved. */
export function GradingCard({ title, description, dirty, tour, children }: GradingCardProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <SettingsSection
      title={title}
      action={
        dirty ? (
          <Badge variant="outline" className="font-normal">
            {t("unsaved")}
          </Badge>
        ) : undefined
      }
    >
      <div className="space-y-4" data-tour={tour}>
        <p className="text-muted-foreground text-sm">{description}</p>
        {children}
      </div>
    </SettingsSection>
  );
}
