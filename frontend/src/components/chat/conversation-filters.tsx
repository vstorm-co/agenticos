"use client";

import { useTranslations } from "next-intl";
import { ArrowDownUp } from "lucide-react";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { SearchInput } from "@/components/ui/list-controls";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents } from "@/hooks";
import type { ConversationSortDir, ConversationSortKey } from "@/hooks/use-conversations";

/** The sort control's value: one string, because a `Select` carries one. */
export type ConversationSort = `${ConversationSortKey}:${ConversationSortDir}`;

export const DEFAULT_SORT: ConversationSort = "updated_at:desc";

/** Every ordering the sidebar offers, and the only strings `?sort=` may hold. */
const SORTS: readonly ConversationSort[] = [
  "updated_at:desc",
  "updated_at:asc",
  "created_at:desc",
  "title:asc",
  "title:desc",
];

export function isConversationSort(value: string | null): value is ConversationSort {
  return SORTS.includes(value as ConversationSort);
}

export function splitSort(sort: ConversationSort): {
  sortBy: ConversationSortKey;
  sortDir: ConversationSortDir;
} {
  const [sortBy, sortDir] = sort.split(":") as [ConversationSortKey, ConversationSortDir];
  return { sortBy, sortDir };
}

interface ConversationFiltersProps {
  search: string;
  onSearchChange: (search: string) => void;
  agentId: string | null;
  onAgentChange: (agentId: string | null) => void;
  sort: ConversationSort;
  onSortChange: (sort: ConversationSort) => void;
  /** Put the cursor in the search box on mount - see the collapsed rail. */
  autoFocusSearch?: boolean;
}

/**
 * Search, agent and sort, above the conversation list.
 *
 * Every one of them is a request rather than a slice of what is on screen: the
 * sidebar holds the pages fetched so far, so a filter applied here would search
 * thirty threads and report nothing for one from March.
 *
 * Archived agents are included in the picker on purpose - a thread answered by
 * an agent that has since been retired is exactly the one somebody comes here
 * looking for. The list is the same query the chat's own agent picker runs, so
 * this costs no extra request, and it is already narrowed to the agents the
 * caller may see.
 */
export function ConversationFilters({
  search,
  onSearchChange,
  agentId,
  onAgentChange,
  sort,
  onSortChange,
  autoFocusSearch = false,
}: ConversationFiltersProps) {
  const t = useTranslations("chat.sidebar");
  const { agents } = useAgents({ includeArchived: true });

  return (
    <div className="space-y-2 px-3 pb-2">
      {/* `sm:w-full` overrides `SearchInput`'s own `sm:w-64`, which is a sensible
          default on the wide pages every other caller sits on and 24px wider
          than this one's content box: the sidebar is `w-64` too, so the input
          hung over its right edge from the `sm` breakpoint up. */}
      <SearchInput
        value={search}
        onChange={onSearchChange}
        placeholder={t("searchPlaceholder")}
        autoFocus={autoFocusSearch}
        className="w-full sm:w-full"
      />
      <div className="flex gap-2">
        {/* "Answered in", not "belongs to". The picker can be changed
            mid-thread, so a thread can match two agents - which is why the
            trigger says what the filter means rather than leaving a reader to
            infer ownership from a name. */}
        <Select
          value={agentId ?? "all"}
          onValueChange={(value) => onAgentChange(value === "all" ? null : value)}
        >
          <SelectTrigger className="h-8 min-w-0 flex-1 text-xs" aria-label={t("agentFilterLabel")}>
            <SelectValue placeholder={t("allAgents")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("allAgents")}</SelectItem>
            {agents.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                <span className="flex items-center gap-2">
                  <AgentAvatar agentId={agent.id} name={agent.name} size="sm" />
                  <span className="truncate">{agent.name}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={sort} onValueChange={(value) => onSortChange(value as ConversationSort)}>
          <SelectTrigger
            className="h-8 w-9 justify-center px-0 [&>svg:last-child]:hidden"
            aria-label={t("sortLabel")}
          >
            <ArrowDownUp className="h-3.5 w-3.5" aria-hidden />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="updated_at:desc">{t("sortRecent")}</SelectItem>
            <SelectItem value="updated_at:asc">{t("sortLeastRecent")}</SelectItem>
            <SelectItem value="created_at:desc">{t("sortNewest")}</SelectItem>
            <SelectItem value="title:asc">{t("sortTitleAsc")}</SelectItem>
            <SelectItem value="title:desc">{t("sortTitleDesc")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {agentId !== null && (
        <p className="text-muted-foreground text-[10px]">{t("agentFilterHint")}</p>
      )}
    </div>
  );
}
