"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";

interface GradingSaveBarProps {
  /** Why the change cannot be saved as it stands, as a sentence; null when it can. */
  problem: string | null;
  saving: boolean;
  onSave: () => void;
  onDiscard: () => void;
}

/**
 * The one place the Grading tab's changes are saved or dropped, held at the
 * bottom of the screen while any card holds one. A change that could grade
 * nothing says so here, where Save is held shut.
 */
export function GradingSaveBar({ problem, saving, onSave, onDiscard }: GradingSaveBarProps) {
  const t = useTranslations("datasets.scoring");
  return (
    <div
      role="region"
      aria-label={t("unsavedChanges")}
      className="bg-background/95 supports-[backdrop-filter]:bg-background/80 sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded-xl border p-3 shadow-lg backdrop-blur"
    >
      {problem === null ? (
        <p className="text-sm font-medium">{t("unsavedChanges")}</p>
      ) : (
        <p role="alert" className="text-destructive text-sm">
          {problem}
        </p>
      )}
      <span className="ml-auto flex items-center gap-2">
        <Button size="sm" variant="outline" disabled={saving} onClick={onDiscard}>
          {t("discard")}
        </Button>
        <Button size="sm" disabled={saving || problem !== null} onClick={onSave}>
          {t("save")}
        </Button>
      </span>
    </div>
  );
}
