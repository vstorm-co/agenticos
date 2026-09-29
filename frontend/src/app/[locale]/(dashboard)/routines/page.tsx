"use client";

import { useState } from "react";
import { CalendarClock, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ScheduledTab } from "@/components/runs/scheduled-tab";
import { NewEventTriggerDialog } from "@/components/triggers/new-event-trigger-dialog";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { useCanCreateTrigger } from "@/hooks";

/**
 * The org-wide home for everything an agent does on its own.
 *
 * It is where a routine is both started and managed: the org-wide list of what is
 * already scheduled, plus the two ways to start one. "New schedule" opens the
 * cadence form; "New event trigger" opens the portal grid in a dialog, the default
 * path to an event trigger - the same dialog and the same label the agent panel and
 * the chat sidebar use, neither of which has a page to navigate to. The create
 * controls are hidden, not
 * disabled, for a caller who may not run an agent; the list still shows, because
 * each row resolves its own controls from its `can_manage`.
 */
export default function RoutinesPage() {
  const t = useTranslations("pages.routines");
  const tt = useTranslations("triggers");
  const canCreate = useCanCreateTrigger();
  const [creatingSchedule, setCreatingSchedule] = useState(false);
  const [creatingEvent, setCreatingEvent] = useState(false);

  return (
    <div className="space-y-6">
      {/* The two ways to start a routine are the page's primary actions, so they
          sit where every other page keeps its create button - in the header. */}
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate ? (
            <div className="flex flex-wrap gap-2" data-tour="routines-create">
              <Button variant="outline" onClick={() => setCreatingEvent(true)}>
                <Zap className="h-4 w-4" />
                {tt("newEvent")}
              </Button>
              <Button onClick={() => setCreatingSchedule(true)}>
                <CalendarClock className="h-4 w-4" />
                {tt("newSchedule")}
              </Button>
            </div>
          ) : undefined
        }
      />

      {/* The anchor is the wrapper, not the table: a card whose body is the whole
          org-wide list spotlights the viewport, which highlights nothing. */}
      <div data-tour="routines-list">
        <ScheduledTab />
      </div>

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
