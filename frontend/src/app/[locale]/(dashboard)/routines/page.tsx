"use client";

import { useState } from "react";
import { CalendarClock, Radar, Zap, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { RoutinesList } from "@/components/triggers/routines-list";
import { NewEventTriggerDialog } from "@/components/triggers/new-event-trigger-dialog";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { WatchDialog } from "@/components/watches/watch-dialog";
import { useCanWatch } from "@/components/watches/watches-card";
import { useCanCreateTrigger } from "@/hooks";

export default function RoutinesPage() {
  const t = useTranslations("pages.routines");
  const canCreate = useCanCreateTrigger();
  const [creatingSchedule, setCreatingSchedule] = useState(false);
  const [creatingEvent, setCreatingEvent] = useState(false);
  const canWatch = useCanWatch();
  const [creatingWatch, setCreatingWatch] = useState(false);

  return (
    <div className="flex flex-1 flex-col space-y-4">
      {/* The two ways to start a routine are the page's primary actions, so they
          sit where every other page keeps its create button - in the header. */}
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate || canWatch ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button data-tour="routines-create">
                  <Plus className="h-4 w-4" />
                  {t("newRoutine")}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canCreate && (
                  <DropdownMenuItem onSelect={() => setCreatingSchedule(true)}>
                    <CalendarClock className="h-4 w-4" />
                    {t("scheduledTask")}
                  </DropdownMenuItem>
                )}
                {canCreate && (
                  <DropdownMenuItem onSelect={() => setCreatingEvent(true)}>
                    <Zap className="h-4 w-4" />
                    {t("eventTask")}
                  </DropdownMenuItem>
                )}
                {canWatch && (
                  <DropdownMenuItem onSelect={() => setCreatingWatch(true)}>
                    <Radar className="h-4 w-4" />
                    {t("newWatch")}
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          ) : undefined
        }
      />

      <div data-tour="routines-list" className="flex flex-1 flex-col">
        <RoutinesList />
      </div>

      {creatingSchedule && (
        <TriggerFormDialog
          agentId={null}
          open
          initialType="schedule"
          onOpenChange={(next) => {
            if (next) return;
            setCreatingSchedule(false);
          }}
        />
      )}

      {creatingWatch && (
        <WatchDialog open onOpenChange={(next) => !next && setCreatingWatch(false)} />
      )}

      {creatingEvent && (
        <NewEventTriggerDialog open onOpenChange={(next) => !next && setCreatingEvent(false)} />
      )}
    </div>
  );
}
