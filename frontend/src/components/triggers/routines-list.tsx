"use client";

import { useState } from "react";
import { CalendarClock, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ErrorState, LoadingState } from "@/components/states";
import { ListCard, ListCardEmpty, Pager, SearchInput, useListControls } from "@/components/ui";
import { WatchRow } from "@/components/watches/watches-card";
import { WatchDialog } from "@/components/watches/watch-dialog";
import { useMcpConnections } from "@/hooks";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { useWatches } from "@/hooks/use-watches";
import { getErrorMessage } from "@/lib/api-error";
import type { Watch } from "@/lib/watches-api";
import type { Trigger } from "@/types/triggers";
import { TriggerRow } from "./trigger-row";

type Routine = { kind: "task"; row: Trigger } | { kind: "monitor"; row: Watch };

export function RoutinesList() {
  const t = useTranslations("triggers");
  const tw = useTranslations("watches");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");
  const tasks = useOrgTriggers();
  const monitoring = useWatches();
  const { connections } = useMcpConnections();
  const [editing, setEditing] = useState<Watch | null>(null);
  const items: Routine[] = [
    ...tasks.triggers.map((row): Routine => ({ kind: "task", row })),
    ...monitoring.watches.map((row): Routine => ({ kind: "monitor", row })),
  ];
  const list = useListControls({
    items,
    matches: (item, query) =>
      (item.kind === "task"
        ? [item.row.name, item.row.agent_name, item.row.prompt]
        : [item.row.title, item.row.instructions, item.row.connection_name]
      ).some((value) => (value ?? "").toLowerCase().includes(query)),
  });
  const error = tasks.error ?? monitoring.error;
  const loading = tasks.isLoading || monitoring.isLoading;
  const act = async (work: () => Promise<unknown>, message: string) => {
    try {
      await work();
      toast.success(message);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };
  return (
    <>
      <ListCard
        fill
        namedByPage
        layout="grid"
        title={t("activityTitle")}
        contentClassName="p-0"
        counted={loading || error ? null : t("routineCount", { count: items.length })}
        controls={
          items.length > 0 && (
            <SearchInput
              value={list.query}
              onChange={list.setQuery}
              placeholder={t("searchRoutines")}
              className="sm:w-56"
            />
          )
        }
      >
        {error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{
              label: tc("retry"),
              onClick: () => {
                void tasks.refetch();
                void monitoring.refetch();
              },
            }}
            className="m-5"
          />
        ) : loading ? (
          <LoadingState variant="skeleton-list" rows={4} />
        ) : items.length === 0 ? (
          <ListCardEmpty
            icon={CalendarClock}
            title={t("activityEmptyTitle")}
            description={t("activityEmptyDescription")}
          />
        ) : (
          <div className="space-y-3">
            {list.visible.length === 0 ? (
              <ListCardEmpty
                icon={Search}
                title={t("noRoutineMatches")}
                description={t("noRoutineMatchesHint")}
                cta={{ label: t("clearSearch"), onClick: () => list.setQuery("") }}
              />
            ) : (
              <ul className="space-y-3">
                {list.visible.map((item) =>
                  item.kind === "task" ? (
                    <li key={`task:${item.row.id}`} className="list-none">
                      <TriggerRow trigger={item.row} showAgent />
                    </li>
                  ) : (
                    <WatchRow
                      className="border-foreground/8 bg-card rounded-xl border"
                      key={`monitor:${item.row.id}`}
                      watch={item.row}
                      lapsed={connections.some(
                        (connection) =>
                          connection.id === item.row.connection_id && !connection.authorized,
                      )}
                      onEdit={() => setEditing(item.row)}
                      onToggle={(on) => {
                        void act(
                          () => monitoring.update({ id: item.row.id, changes: { is_active: on } }),
                          tw(on ? "resumed" : "paused"),
                        );
                      }}
                      onRemove={() => {
                        void act(() => monitoring.remove(item.row.id), tw("removed"));
                      }}
                    />
                  ),
                )}
              </ul>
            )}
            <Pager
              page={list.page}
              pageCount={list.pageCount}
              matched={list.matched}
              total={list.total}
              onPage={list.setPage}
              counted={t("routineCount", { count: list.total })}
            />
          </div>
        )}
      </ListCard>
      {editing && (
        <WatchDialog
          open
          watch={editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        />
      )}
    </>
  );
}
