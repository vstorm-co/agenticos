"use client";

import { CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerRow } from "@/components/triggers/trigger-row";
import { ErrorState, LoadingState } from "@/components/states";
import { SectionGlyph } from "@/components/states/section-glyph";
import { ListCard, Pager, SearchInput, useListControls } from "@/components/ui";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { getErrorMessage } from "@/lib/api-error";

/**
 * Every schedule and event trigger across the organization - the body of the
 * Routines page.
 *
 * A failed request is said out loud rather than drawn as "nothing runs on its
 * own": that page fans out to several queries and an empty list and a 502 are the
 * same pixels, so the error is its own state. Each row gates its own controls on
 * the trigger's `can_manage`, resolved per row by the server, and the list itself
 * only carries triggers on agents the caller may already see.
 *
 * The page header already says what the list is, so the card's own header is a
 * toolbar - how many there are, and the search box.
 *
 * Nothing scheduled is not a card. An empty box half a screen tall, with a
 * button that sent the reader to the agents list to work out what to do there,
 * stood between the page and the ideas that answer "what could this be for" -
 * so the empty state is one quiet line over them, and the header's own New
 * schedule is the way in.
 *
 * Searched and paged on this side, because the request already holds the whole
 * list: `useOrgTriggers` walks every page of `GET /triggers` into one array so a
 * deployment past the server's page cap does not silently lose its tail. That
 * makes a round trip per keystroke the slower design - and it makes paging
 * necessary rather than optional, since an organization with sixty routines was
 * rendering all sixty rows into one scroll.
 */
export function ScheduledTab() {
  const t = useTranslations("triggers");
  const tErrors = useTranslations("errors");
  const { triggers, isLoading, isError, error } = useOrgTriggers();
  const list = useListControls({
    items: triggers,
    // Name, agent and prompt: what somebody scanning for one routine among sixty
    // actually remembers about it. The cadence is not searched - "every 15
    // minutes" is a rendered phrase, not a stored string.
    matches: (trigger, query) =>
      [trigger.name, trigger.agent_name, trigger.prompt].some((field) =>
        (field ?? "").toLowerCase().includes(query),
      ),
  });

  if (!isLoading && !isError && triggers.length === 0) {
    return (
      <div className="flex flex-col items-center px-6 py-10 text-center">
        <SectionGlyph icon={CalendarClock} />
        <p className="text-foreground mt-4 text-sm font-medium">{t("activityEmptyTitle")}</p>
        <p className="text-muted-foreground mt-1 max-w-sm text-sm">
          {t("activityEmptyDescription")}
        </p>
      </div>
    );
  }

  return (
    <ListCard
      namedByPage
      title={t("activityTitle")}
      counted={isLoading ? null : t("routineCount", { count: triggers.length })}
      contentClassName="p-0"
      controls={
        triggers.length > 0 && (
          <SearchInput
            value={list.query}
            onChange={list.setQuery}
            placeholder={t("searchRoutines")}
            className="sm:w-56"
          />
        )
      }
    >
      {isLoading ? (
        <LoadingState variant="skeleton-table" columns={1} rows={4} className="m-5" />
      ) : isError ? (
        <ErrorState description={getErrorMessage(error, tErrors)} className="m-5" />
      ) : (
        <div className="space-y-3 p-5">
          {list.visible.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("noRoutineMatches")}</p>
          ) : (
            list.visible.map((trigger) => (
              <TriggerRow key={trigger.id} trigger={trigger} showAgent />
            ))
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
  );
}
