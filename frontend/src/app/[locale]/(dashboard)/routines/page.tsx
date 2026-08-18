"use client";

import { useState } from "react";
import { CalendarClock, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ScheduledTab } from "@/components/runs/scheduled-tab";
import { NewEventTriggerDialog } from "@/components/triggers/new-event-trigger-dialog";
import { PortalsTab } from "@/components/triggers/portals-tab";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

/**
 * The org-wide home for everything an agent does on its own.
 *
 * It is where a routine is both started and managed, so it carries the Split New -
 * a schedule opens the cadence form, an event trigger opens the portal grid, the
 * default path - the org-wide list of what is already scheduled, and the portal
 * grid inline for browsing services and connecting the organization's accounts.
 * The create controls are hidden, not disabled, for a caller who may not run an
 * agent; the list still shows, because each row resolves its own controls from its
 * `can_manage`. The read-only "Scheduled" view under Activity stays as it was.
 */
export default function RoutinesPage() {
  const t = useTranslations("pages.routines");
  const tt = useTranslations("triggers");
  const { can } = usePermissions();
  const canCreate = can(Perm.agentsRun);
  const [creatingSchedule, setCreatingSchedule] = useState(false);
  const [creatingEvent, setCreatingEvent] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("description")} />

      {canCreate && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setCreatingSchedule(true)}>
            <CalendarClock className="mr-2 h-4 w-4" />
            {tt("newSchedule")}
          </Button>
          <Button variant="outline" onClick={() => setCreatingEvent(true)}>
            <Zap className="mr-2 h-4 w-4" />
            {tt("newEvent")}
          </Button>
        </div>
      )}

      <ScheduledTab />
      <PortalsTab />

      {creatingSchedule && (
        <TriggerFormDialog
          agentId={null}
          open
          initialType="schedule"
          onOpenChange={(next) => !next && setCreatingSchedule(false)}
        />
      )}
      {creatingEvent && (
        <NewEventTriggerDialog open onOpenChange={(next) => !next && setCreatingEvent(false)} />
      )}
    </div>
  );
}
