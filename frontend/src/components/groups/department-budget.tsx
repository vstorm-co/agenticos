"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { HeadroomBar } from "@/components/dashboard/widgets/budget-headroom";
import { formatUsd } from "@/components/dashboard/format";
import { ErrorState } from "@/components/states";
import { Button, Figure, ListCard } from "@/components/ui";
import { useGroupSpend } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { saveBlob } from "@/lib/file-access";
import { downloadGroupSpend } from "@/lib/groups-api";
import type { Group } from "@/types/groups";

/**
 * A department's month on its own page: what its members' runs cost against its
 * cap, and the month as CSV, a row per member and agent (#2072).
 *
 * Mounted only for a reader holding `runs:view`, who is who the endpoint answers.
 */
export function DepartmentBudget({ orgId, group }: { orgId: string; group: Group }) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const { spend, isLoading, error } = useGroupSpend(orgId);
  const [saving, setSaving] = useState(false);
  const row = spend?.items.find((item) => item.group_id === group.id);
  const used = Number(row?.spent_usd ?? 0);
  const cap = group.monthly_budget_usd === null ? null : Number(group.monthly_budget_usd);

  const download = async () => {
    setSaving(true);
    try {
      saveBlob(await downloadGroupSpend(orgId, group.id), `${group.name}-spend.csv`);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    } finally {
      setSaving(false);
    }
  };

  return (
    <ListCard
      title={t("thisMonth")}
      counted={isLoading || error ? null : t("runCount", { count: row?.run_count ?? 0 })}
      controls={
        <Button variant="outline" size="sm" disabled={saving} onClick={() => void download()}>
          <Download className="size-3.5" aria-hidden />
          {t("exportCsv")}
        </Button>
      }
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : (
        <div className="space-y-3">
          <Figure
            value={formatUsd(used)}
            caption={
              cap === null
                ? t("noCapSpent")
                : t("ofCap", { cap: formatUsd(cap), left: formatUsd(Math.max(cap - used, 0)) })
            }
          />
          {cap !== null && <HeadroomBar used={used} cap={cap} />}
        </div>
      )}
    </ListCard>
  );
}
