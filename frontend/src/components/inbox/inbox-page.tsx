"use client";

import { useRouter } from "next/navigation";
import {
  CheckCheck,
  CircleAlert,
  Inbox as InboxIcon,
  Radar,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { useUrlState } from "@/hooks/use-url-state";
import { SuggestionMark } from "@/components/chat/suggestion-actions";
import { PageHeader } from "@/components/dashboard/page-header";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { Badge, Button, ListCard, ListCardEmpty } from "@/components/ui";
import { useSuggestionHistory, useSuggestions } from "@/hooks/use-suggestions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { Suggestion } from "@/lib/suggestions-api";
import { timeAgo } from "@/lib/utils";
import { SuggestionRows } from "./suggestion-rows";

type Filter = "all" | "urgent" | "watches" | "suggestions" | "done";

const FILTERS: Filter[] = ["all", "urgent", "watches", "suggestions", "done"];

const FILTER_ICONS: Record<Filter, LucideIcon> = {
  all: InboxIcon,
  urgent: CircleAlert,
  watches: Radar,
  suggestions: Sparkles,
  done: CheckCheck,
};

const KEEPS: Record<Exclude<Filter, "done">, (item: Suggestion) => boolean> = {
  all: () => true,
  urgent: (item) => item.urgent === true,
  watches: (item) => item.kind === "finding",
  suggestions: (item) => item.kind !== "finding",
};

/** `?filter=watches` from the Watches card opens the inbox already narrowed. */
function initialFilter(param: string | null): Filter {
  return FILTERS.find((each) => each === param) ?? "all";
}

/**
 * Everything the platform brought the person on its own (#2301): what their
 * watches found and what the nightly look proposed, open ones to act on and,
 * under Done, what they already took or declined - with the way back. One card,
 * read like a mailbox: the filters in its header, a row per item.
 */
export function InboxPage() {
  const t = useTranslations("inbox");
  const ts = useTranslations("common");
  const { suggestions, isLoading, error, refetch } = useSuggestions();
  const [asked, setFilter] = useUrlState("filter");
  const filter = initialFilter(asked);
  const open = filter === "done" ? [] : suggestions.filter(KEEPS[filter]);

  return (
    <div className="flex flex-1 flex-col space-y-6">
      <PageHeader title={t("title")} description={t("description")} />
      <ListCard
        fill
        namedByPage
        title={t("title")}
        counted={isLoading ? null : error ? "—" : t("waiting", { count: suggestions.length })}
        contentClassName="p-0"
        headerTour="inbox-filters"
        controls={
          <>
            <span id="inbox-filter-label" className="sr-only">
              {t("filterLabel")}
            </span>
            <ChoiceGroup<Filter>
              labelledBy="inbox-filter-label"
              value={filter}
              onChange={(next) => setFilter(next === "all" ? null : next)}
              options={FILTERS.map((value) => ({
                value,
                label: t(`filter.${value}`),
                icon: FILTER_ICONS[value],
              }))}
            />
          </>
        }
      >
        {filter === "done" ? (
          <Decided />
        ) : isLoading ? (
          <LoadingState variant="skeleton-list" rows={3} className="p-5" />
        ) : error ? (
          <ErrorState
            className="m-5 flex-1"
            cta={{ label: ts("retry"), onClick: () => void refetch() }}
          />
        ) : open.length === 0 ? (
          <Nothing filter={filter} />
        ) : (
          <SuggestionRows items={open} />
        )}
      </ListCard>
    </div>
  );
}

/** Nothing waits: where things come from, and for watches where they are set up. */
function Nothing({ filter }: { filter: Exclude<Filter, "done"> }) {
  const t = useTranslations("inbox");
  const router = useRouter();
  return (
    <ListCardEmpty
      icon={InboxIcon}
      title={t("empty.title")}
      description={t("empty.description")}
      cta={
        filter === "all" || filter === "watches"
          ? {
              label: t("empty.watches"),
              onClick: () => router.push(`${ROUTES.ROUTINES}?tab=watches`),
            }
          : undefined
      }
    />
  );
}

/** What the person already answered, newest first, and a way back for what they declined. */
function Decided() {
  const t = useTranslations("inbox");
  const tStatus = useTranslations("assistantSettings.suggestions");
  const tErrors = useTranslations("errors");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const ts = useTranslations("common");
  const { history, restore, isLoading, error, refetch } = useSuggestionHistory();
  if (isLoading) return <LoadingState variant="skeleton-list" rows={3} className="p-5" />;
  if (error)
    return (
      <ErrorState
        className="m-5 flex-1"
        cta={{ label: ts("retry"), onClick: () => void refetch() }}
      />
    );
  const decided = history.filter((item) => item.status !== "open");
  if (decided.length === 0) {
    return <ListCardEmpty icon={InboxIcon} title={t("doneEmpty")} />;
  }
  const bringBack = async (id: string) => {
    try {
      await restore(id);
      toast.success(tStatus("restored"));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };
  return (
    <ul className="divide-border divide-y">
      {decided.map((item) => (
        <li key={item.id} className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <SuggestionMark suggestion={item} className="bg-muted opacity-60 shadow-none" />
          <div className="min-w-0 flex-1">
            <p className="text-muted-foreground truncate text-sm">{item.title}</p>
            {item.detail && <p className="text-muted-foreground truncate text-xs">{item.detail}</p>}
          </div>
          <span className="text-muted-foreground hidden shrink-0 text-xs sm:inline">
            {timeAgo(item.created_at, tTime, locale)}
          </span>
          <Badge variant="secondary">{tStatus(`status.${item.status}`)}</Badge>
          {item.status === "dismissed" && (
            <Button size="sm" variant="outline" onClick={() => bringBack(item.id)}>
              {tStatus("restore")}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
