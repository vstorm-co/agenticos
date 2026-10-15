"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui";

interface GradingCardProps {
  title: string;
  description: string;
  /** Whether this card holds a change not yet saved; its Save button shows only then. */
  dirty: boolean;
  /** False while the change cannot be saved, or while a save is running. */
  canSave: boolean;
  onSave: () => void;
  tour?: string;
  children: ReactNode;
}

/** One part of a dataset's grading, saved on its own beside the fields it changed. */
export function GradingCard({
  title,
  description,
  dirty,
  canSave,
  onSave,
  tour,
  children,
}: GradingCardProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <SettingsSection
      title={title}
      description={description}
      action={
        dirty ? (
          <Button size="sm" disabled={!canSave} onClick={onSave}>
            {t("save")}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-4" data-tour={tour}>
        {children}
      </div>
    </SettingsSection>
  );
}
