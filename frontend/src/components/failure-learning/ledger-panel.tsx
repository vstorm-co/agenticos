"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Card,
  CardContent,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { LedgerEntryRead, LedgerStatus } from "@/lib/failure-learning-api";
import { cn } from "@/lib/utils";

const STATUSES: LedgerStatus[] = ["draft", "open", "dismissed", "resolved"];

/** A module table holds keys, and the component translates at the point of use. */
const STATUS_LABEL: Record<
  LedgerStatus,
  "statusDraft" | "statusOpen" | "statusDismissed" | "statusResolved"
> = {
  draft: "statusDraft",
  open: "statusOpen",
  dismissed: "statusDismissed",
  resolved: "statusResolved",
};

/**
 * The ledger: one row per recurring mistake, newest first, with a status
 * filter. Model-scoped entries list beside the agent's own - they are
 * pattern records for the whole organization, and their proposals are
 * per-agent. Selecting a row is what the detail below reads.
 */
export function LedgerPanel({
  entries,
  isLoading,
  error,
  selectedId,
  onSelect,
}: {
  entries: LedgerEntryRead[];
  isLoading: boolean;
  error: Error | null;
  selectedId: string | null;
  onSelect: (entryId: string) => void;
}) {
  const t = useTranslations("failureLearning");
  const [filter, setFilter] = useState<LedgerStatus | "all">("all");
  const shown = filter === "all" ? entries : entries.filter((entry) => entry.status === filter);

  if (isLoading) return <LoadingState variant="skeleton-list" />;
  if (error) return <ErrorState />;
  if (entries.length === 0) return <EmptyState title={t("noEntries")} />;
  return (
    <div className="space-y-3">
      <Select value={filter} onValueChange={(value) => setFilter(value as LedgerStatus | "all")}>
        <SelectTrigger className="w-48" aria-label={t("statusAll")}>
          <SelectValue placeholder={t("statusAll")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">{t("statusAll")}</SelectItem>
          {STATUSES.map((status) => (
            <SelectItem key={status} value={status}>
              {t(STATUS_LABEL[status])}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {shown.map((entry) => (
        <Card
          key={entry.id}
          className={cn("cursor-pointer", selectedId === entry.id && "border-primary")}
        >
          <CardContent
            className="flex flex-wrap items-center gap-3 p-4"
            onClick={() => onSelect(entry.id)}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === "Enter") onSelect(entry.id);
            }}
          >
            <div className="min-w-0 flex-1">
              <p className="font-medium break-words">{entry.title}</p>
              <p className="text-muted-foreground text-sm">
                {entry.scope === "model" ? entry.model : entry.pattern_key} ·{" "}
                {t("entryCases", { count: entry.eval_case_count })} ·{" "}
                {t("entryProposals", { count: entry.proposal_count })}
                {entry.open_since
                  ? ` · ${t("openSince", { date: entry.open_since.slice(0, 10) })}`
                  : ""}
              </p>
            </div>
            <Badge variant="secondary">{t(STATUS_LABEL[entry.status])}</Badge>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
