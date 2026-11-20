"use client";

import { useId, useState, type ReactNode } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import type { MessagePart } from "@/types";
import type { PartRun } from "./turn-parts";

const FILTERS = ["all", "tools", "thinking", "errors", "messages"] as const;
export type TraceFilter = (typeof FILTERS)[number];

function needsAttention(part: MessagePart): boolean {
  return (
    part.type === "model_setup" ||
    part.toolCall?.status === "awaiting_approval" ||
    part.toolCall?.status === "awaiting_answer" ||
    (part.type === "ask_user" && !part.answer?.trim())
  );
}

function matches(part: MessagePart, query: string, filter: TraceFilter): boolean {
  const kindMatches =
    filter === "all" ||
    (filter === "tools" && part.type === "tool") ||
    (filter === "thinking" && part.type === "thinking") ||
    (filter === "errors" &&
      (part.toolCall?.status === "error" || Boolean(part.workflowRun?.error))) ||
    (filter === "messages" && part.type !== "tool" && part.type !== "thinking");
  // Parts come from the JSON transcript. Search the same text, arguments and
  // results that the reader can already open; no new read or server query.
  return kindMatches && (query === "" || JSON.stringify(part).toLowerCase().includes(query));
}

/** Retain chronology and original live-part flags; filtering never changes a turn. */
export function filterTrace(runs: PartRun[], search: string, filter: TraceFilter) {
  const query = search.trim().toLowerCase();
  let total = 0;
  let shown = 0;
  let attention = 0;
  const keep = (part: MessagePart) => {
    total += 1;
    const match = matches(part, query, filter);
    const pinned = !match && needsAttention(part);
    if (!match && !pinned) return false;
    shown += 1;
    if (pinned) attention += 1;
    return true;
  };
  const filtered: PartRun[] = [];
  for (const run of runs) {
    if (run.kind === "other") {
      if (keep(run.part)) filtered.push(run);
    } else {
      const parts = run.parts.filter(keep);
      if (parts.length > 0)
        filtered.push({ ...run, parts: parts as [MessagePart, ...MessagePart[]] });
    }
  }
  return { runs: filtered, total, shown, attention };
}

/** An opt-in local filter inside a turn's existing work disclosure. */
export function TurnTrace({
  runs,
  render,
}: {
  runs: PartRun[];
  render: (run: PartRun, index: number, visible: PartRun[]) => ReactNode;
}) {
  const t = useTranslations("chat.trace");
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<TraceFilter>("all");
  const controlsId = useId();
  const searchId = useId();
  const filterId = useId();
  const result = filterTrace(runs, search, filter);
  const active = search.trim() !== "" || filter !== "all";
  const clear = () => {
    setSearch("");
    setFilter("all");
  };
  return (
    <>
      <div data-tour="chat-trace-filter">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-expanded={open}
          aria-controls={open ? controlsId : undefined}
          onClick={() => {
            if (open) clear();
            setOpen(!open);
          }}
        >
          <Search className="size-3.5" aria-hidden />
          {t("toggle")}
        </Button>
        {open && (
          <div
            id={controlsId}
            role="search"
            aria-label={t("title")}
            className="border-border my-2 space-y-2 rounded-lg border p-3"
            onKeyDown={(event) => {
              if (event.key === "Escape" && active) {
                event.preventDefault();
                event.stopPropagation();
                clear();
              }
            }}
          >
            <div className="flex flex-wrap items-end gap-2">
              <label htmlFor={searchId} className="min-w-0 flex-1 space-y-1 text-xs">
                <span>{t("search")}</span>
                <input
                  id={searchId}
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  className="border-input h-9 w-full rounded-md border bg-transparent px-2 text-sm"
                />
              </label>
              <label htmlFor={filterId} className="space-y-1 text-xs">
                <span className="block">{t("filter")}</span>
                <select
                  id={filterId}
                  value={filter}
                  onChange={(event) => setFilter(event.target.value as TraceFilter)}
                  className="border-input bg-background h-9 rounded-md border px-2 text-sm"
                >
                  {FILTERS.map((value) => (
                    <option key={value} value={value}>
                      {t(value)}
                    </option>
                  ))}
                </select>
              </label>
              {active && (
                <Button type="button" variant="ghost" size="sm" onClick={clear}>
                  {t("clear")}
                </Button>
              )}
            </div>
            <p role="status" className="text-muted-foreground text-xs">
              {t("count", { shown: result.shown, total: result.total })}
            </p>
            {result.attention > 0 && (
              <p className="text-muted-foreground text-xs">{t("attention")}</p>
            )}
          </div>
        )}
      </div>
      {result.shown === 0 ? (
        <p className="text-muted-foreground px-2 text-sm">{t("noMatches")}</p>
      ) : (
        result.runs.map((run, index) => render(run, index, result.runs))
      )}
    </>
  );
}
