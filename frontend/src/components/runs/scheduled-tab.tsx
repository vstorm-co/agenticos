"use client";

import { CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerRow } from "@/components/triggers/trigger-row";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";

/**
 * Every schedule and event trigger across the organization, on the Activity page.
 *
 * A failed request is said out loud rather than drawn as "nothing scheduled":
 * this page fans out to several queries and an empty list and a 502 are the same
 * pixels, so the error is its own state. Managing a row is gated on the
 * role-level `agents:run`; the server still resolves it per row, and the list
 * itself only carries triggers on agents the caller may already see.
 */
export function ScheduledTab() {
  const t = useTranslations("triggers");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { triggers, isLoading, isError, error } = useOrgTriggers();
  const canManage = can(Perm.agentsRun);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("activityTitle")}</CardTitle>
        <CardDescription>{t("activityDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState variant="skeleton-table" columns={1} rows={4} />
        ) : isError ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : triggers.length === 0 ? (
          <EmptyState
            icon={CalendarClock}
            title={t("activityEmptyTitle")}
            description={t("activityEmptyDescription")}
          />
        ) : (
          <div className="space-y-3">
            {triggers.map((trigger) => (
              <TriggerRow key={trigger.id} trigger={trigger} canManage={canManage} showAgent />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
