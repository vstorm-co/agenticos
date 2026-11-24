"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { DatasetCase } from "@/types/datasets";

interface CaseTwinNoticeProps {
  /** The case already asking the question the new one asks. */
  twin: DatasetCase;
  onOpen: () => void;
  onAddAnyway: () => void;
  busy: boolean;
}

/** Says a new case asks what one already asks, before a second copy is saved. */
export function CaseTwinNotice({ twin, onOpen, onAddAnyway, busy }: CaseTwinNoticeProps) {
  const t = useTranslations("datasets");
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm"
    >
      <p className="min-w-0 flex-1">
        {t("caseTwin")} <span className="text-muted-foreground italic">{twin.input}</span>
      </p>
      <Button size="sm" variant="outline" onClick={onOpen}>
        {t("caseTwinOpen")}
      </Button>
      <Button size="sm" disabled={busy} onClick={onAddAnyway}>
        {t("caseTwinAddAnyway")}
      </Button>
    </div>
  );
}
