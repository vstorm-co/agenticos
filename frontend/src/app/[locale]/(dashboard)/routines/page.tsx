"use client";

import { useState } from "react";
import { CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ScheduledTab } from "@/components/runs/scheduled-tab";
import { PortalsTab } from "@/components/triggers/portals-tab";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { useCanCreateTrigger } from "@/hooks";

/**
 * The org-wide home for everything an agent does on its own.
 *
 * It is where a routine is both started and managed: the org-wide list of what is
 * already scheduled, and the portal grid inline for browsing services, connecting
 * the organization's accounts, and starting an event trigger from a preset. A
 * schedule is the one path the grid does not cover, so it keeps a "New schedule"
 * button; the event path is the grid itself, so there is no separate button for
 * it here - unlike the agent panel and the chat sidebar, which have no inline grid
 * and open it in a dialog. The create controls are hidden, not disabled, for a
 * caller who may not run an agent; the list still shows, because each row resolves
 * its own controls from its `can_manage`. The read-only "Scheduled" view under
 * Activity stays as it was.
 */
export default function RoutinesPage() {
  const t = useTranslations("pages.routines");
  const tt = useTranslations("triggers");
  const canCreate = useCanCreateTrigger();
  const [creatingSchedule, setCreatingSchedule] = useState(false);

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("description")} />

      {canCreate && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => setCreatingSchedule(true)}>
            <CalendarClock className="mr-2 h-4 w-4" />
            {tt("newSchedule")}
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
    </div>
  );
}
