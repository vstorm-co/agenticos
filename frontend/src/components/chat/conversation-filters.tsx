"use client";

import { useTranslations } from "next-intl";
import { ListFilter, ChevronDown } from "lucide-react";

import {
  Button,
  Label,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
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
  agentId: string | null;
  onAgentChange: (agentId: string | null) => void;
  sort: ConversationSort;
  onSortChange: (sort: ConversationSort) => void;
  /** Leave out conversations an API key's runs opened. */
  hideApi: boolean;
  onHideApiChange: (hide: boolean) => void;
  /** The active threads or the archive. */
  view: "active" | "archived";
  onViewChange: (view: "active" | "archived") => void;
  /** Open beside the button rather than under it - from the collapsed rail. */
  beside?: boolean;
}

/**
 * Everything that narrows the list, behind one button.
 *
 * Every one of them is a request rather than a slice of what is on screen: the
 * sidebar holds the pages fetched so far, so a filter applied here would search
 * thirty threads and report nothing for one from March.
 *
 * One icon, the way the chat products people already use draw it, whose dot
 * says when anything narrows or reorders the list; search opens a window of
 * its own beside it. It used to be six controls stacked over the threads - an agent picker,
 * a sort, an API switch, an active/archived toggle and a count - which pushed
 * the conversations themselves a third of the way down the column.
 *
 * Archived agents are included in the picker on purpose - a thread answered by
 * an agent that has since been retired is exactly the one somebody comes here
 * looking for. The list is the same query the chat's own agent picker runs, so
 * this costs no extra request, and it is already narrowed to the agents the
 * caller may see.
 */
export function ConversationFilters({
  agentId,
  onAgentChange,
  sort,
  onSortChange,
  hideApi,
  onHideApiChange,
  view,
  onViewChange,
  beside = false,
}: ConversationFiltersProps) {
  const t = useTranslations("chat.sidebar");
  const { agents } = useAgents({ includeArchived: true });
  const narrowed = agentId !== null || !hideApi || sort !== DEFAULT_SORT || view === "archived";

  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={t("filters")}
          title={t("filters")}
          className={
            beside
              ? "size-8 p-0"
              : "text-muted-foreground hover:text-foreground h-8 w-full justify-start gap-2 rounded-lg text-xs"
          }
        >
          <ListFilter className="size-3.5" aria-hidden />
          {!beside && <span className="min-w-0 flex-1 truncate text-left">{t("filters")}</span>}
          {narrowed && (
            <span aria-hidden className="bg-foreground size-1.5 shrink-0 rounded-full" />
          )}
          {!beside && <ChevronDown className="text-muted-foreground size-3.5" aria-hidden />}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        side={beside ? "right" : "bottom"}
        align="start"
        sideOffset={8}
        aria-label={t("filters")}
        className="w-80 space-y-5 p-4"
      >
        <div className="flex gap-5 border-b" role="group" aria-label={t("show")}>
          {(["active", "archived"] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={view === option}
              onClick={() => onViewChange(option)}
              className={
                view === option
                  ? "border-foreground border-b-2 pb-2.5 text-sm font-medium"
                  : "text-muted-foreground hover:text-foreground border-b-2 border-transparent pb-2.5 text-sm"
              }
            >
              {t(option)}
            </button>
          ))}
        </div>
        <div className="space-y-1.5">
          {/* "Answered in", not "belongs to". The picker can be changed
                mid-thread, so a thread can match two agents - which is why the
                hint says what the filter means rather than leaving a reader to
                infer ownership from a name. */}
          <Label htmlFor="conversation-agent" className="text-muted-foreground text-xs">
            {t("agentFilterLabel")}
          </Label>
          <Select
            value={agentId ?? "all"}
            onValueChange={(value) => onAgentChange(value === "all" ? null : value)}
          >
            <SelectTrigger id="conversation-agent" aria-label={t("agentFilterLabel")}>
              <SelectValue placeholder={t("allAgents")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allAgents")}</SelectItem>
              {agents.map((agent) => (
                <SelectItem key={agent.id} value={agent.id}>
                  <span className="flex items-center gap-2">
                    <AgentAvatar
                      agentId={agent.id}
                      slug={agent.slug}
                      hasAvatar={agent.has_avatar}
                      colorSlot={agent.avatar_color}
                      size="sm"
                    />
                    <span className="truncate">{agent.name}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {agentId !== null && (
            <p className="text-muted-foreground text-xs">{t("agentFilterHint")}</p>
          )}
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="conversation-sort" className="text-muted-foreground text-xs">
            {t("sortLabel")}
          </Label>
          <Select value={sort} onValueChange={(value) => onSortChange(value as ConversationSort)}>
            <SelectTrigger id="conversation-sort" aria-label={t("sortLabel")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated_at:desc">{t("sortRecent")}</SelectItem>
              <SelectItem value="updated_at:asc">{t("sortLeastRecent")}</SelectItem>
              <SelectItem value="created_at:desc">{t("sortNewest")}</SelectItem>
              <SelectItem value="title:asc">{t("sortTitleAsc")}</SelectItem>
              <SelectItem value="title:desc">{t("sortTitleDesc")}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        {/* A script's threads beside a person's: shown, labelled, and one
              switch from out of the way (#2122). */}
        <label className="flex items-center justify-between gap-4 border-t pt-4 text-[13px]">
          {t("apiFilterLabel")}
          <Switch checked={hideApi} onCheckedChange={onHideApiChange} aria-label={t("hideApi")} />
        </label>
      </PopoverContent>
    </Popover>
  );
}
