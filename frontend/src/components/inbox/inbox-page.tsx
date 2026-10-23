"use client";

import { useState } from "react";
import { Inbox as InboxIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SuggestionCards } from "@/components/chat/suggestion-cards";
import { PageHeader } from "@/components/dashboard/page-header";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { EmptyState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { useSuggestionHistory, useSuggestions } from "@/hooks/use-suggestions";
import { getErrorMessage } from "@/lib/api-error";
import type { Suggestion } from "@/lib/suggestions-api";

type Filter = "all" | "urgent" | "watches" | "suggestions" | "done";

const KEEPS: Record<Exclude<Filter, "done">, (item: Suggestion) => boolean> = {
  all: () => true,
  urgent: (item) => item.urgent === true,
  watches: (item) => item.kind === "finding",
  suggestions: (item) => item.kind !== "finding",
};

/**
 * Everything the platform brought the person on its own (#2301): what their
 * watches found and what the nightly look proposed, open ones to act on and,
 * under Done, what they already took or declined - with the way back.
 */
export function InboxPage() {
  const t = useTranslations("inbox");
  const { suggestions } = useSuggestions();
  const [filter, setFilter] = useState<Filter>("all");
  const open = filter === "done" ? [] : suggestions.filter(KEEPS[filter]);

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("description")} />
      <div data-tour="inbox-filters">
        <ChoiceGroup<Filter>
          labelledBy="inbox-filter-label"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: t("filter.all", { count: suggestions.length }) },
            { value: "urgent", label: t("filter.urgent") },
            { value: "watches", label: t("filter.watches") },
            { value: "suggestions", label: t("filter.suggestions") },
            { value: "done", label: t("filter.done") },
          ]}
        />
        <span id="inbox-filter-label" className="sr-only">
          {t("filterLabel")}
        </span>
      </div>
      {filter === "done" ? (
        <Decided />
      ) : open.length === 0 ? (
        <EmptyState
          icon={InboxIcon}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <SuggestionCards agentId={null} items={open} className="max-w-3xl" />
      )}
    </div>
  );
}

/** What the person already answered, newest first, and a way back for what they declined. */
function Decided() {
  const t = useTranslations("inbox");
  const tStatus = useTranslations("assistantSettings.suggestions");
  const tErrors = useTranslations("errors");
  const { history, restore } = useSuggestionHistory();
  const decided = history.filter((item) => item.status !== "open");
  if (decided.length === 0) {
    return <EmptyState icon={InboxIcon} title={t("doneEmpty")} />;
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
    <ul className="divide-foreground/10 max-w-3xl divide-y">
      {decided.map((item) => (
        <li key={item.id} className="flex items-center gap-3 py-2.5">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{item.title}</p>
            {item.detail && <p className="text-muted-foreground truncate text-xs">{item.detail}</p>}
          </div>
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
