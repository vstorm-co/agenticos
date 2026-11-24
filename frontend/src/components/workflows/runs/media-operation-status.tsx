"use client";

import { useTranslations } from "next-intl";

import { formatCostUsd } from "@/lib/utils";
import type { WorkflowMediaOperationRead, WorkflowMediaRetryEffect } from "@/lib/workflows/types";

/** Operation and accounting facts are independent of the workflow step's final status. */
export function MediaOperationStatus({ operation }: { operation: WorkflowMediaOperationRead }) {
  const t = useTranslations("pages.workflows");
  const amount = (value: string) => formatCostUsd(Number(value));
  return (
    <section aria-label={t("mediaOperationTitle")} className="space-y-2 px-2 py-1 text-xs">
      <p className="font-medium">{t(`mediaOperationPhase.${operation.phase}`)}</p>
      <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1">
        <dt className="text-muted-foreground">{t("mediaOperationHeld")}</dt>
        <dd className="tabular-nums">{amount(operation.held_usd)}</dd>
        <dt className="text-muted-foreground">
          {t(
            operation.cost_source === "catalog_estimate"
              ? "mediaOperationEstimated"
              : "mediaOperationIncurred",
          )}
        </dt>
        <dd className="tabular-nums">{amount(operation.incurred_usd)}</dd>
        <dt className="text-muted-foreground">{t("mediaOperationBooked")}</dt>
        <dd className="tabular-nums">{amount(operation.booked_usd)}</dd>
      </dl>
      {!operation.accounting_complete && (
        <p className="text-muted-foreground">{t("mediaOperationAccountingPending")}</p>
      )}
      {Number(operation.node_unresolved_usd) > 0 && (
        <p className="text-warning">
          {t("mediaOperationUnresolved", { amount: amount(operation.node_unresolved_usd) })}
        </p>
      )}
      {operation.has_receipt && (
        <p className="text-muted-foreground">{t("mediaOperationReceipt")}</p>
      )}
    </section>
  );
}

export function MediaRetryNotice({ effect }: { effect: WorkflowMediaRetryEffect }) {
  const t = useTranslations("pages.workflows");
  return <p className="text-muted-foreground text-sm">{t(`mediaRetryEffect.${effect}`)}</p>;
}
