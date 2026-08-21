"use client";

import { useMemo, useState } from "react";

import {
  DataTable,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Switch,
  type Column,
} from "@/components/ui";
import { useSandboxEvents } from "@/hooks";
import type { SandboxEvent } from "@/lib/sandbox-connections-api";
import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/** The "no filter" value. A `Select` cannot hold `""`, but it can hold this. */
const ANY = "__any__";

interface ActivityLogProps {
  connectionId: string;
  sessionId: string;
}

/**
 * Seconds since an event, as a person reads them.
 *
 * The clock is read here rather than in the component: calling `Date.now()`
 * during a render is impure and the React rule refuses it, which is why
 * `timeAgo` in `lib/utils` is shaped the same way. Two rows measured a
 * microsecond apart is not a difference anybody can see.
 */
function ago(at: number): string {
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - at));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

/**
 * What was done to one sandbox.
 *
 * Paths and commands, never their contents or output — the service does not
 * record those, which is what keeps this from becoming a way to read an agent's
 * work rather than audit it.
 *
 * **Newest first, and each entry says when.** The service answers in the order it
 * recorded them, and a log read to find out what a sandbox is doing *now* had the
 * answer at the bottom of a scroll box - with no timestamp on any row, so "now"
 * and "an hour ago" looked identical. A failed operation gets a mark of its own
 * rather than only red text, which says nothing to anybody who cannot see the
 * difference.
 */
export function ActivityLog({ connectionId, sessionId }: ActivityLogProps) {
  const t = useTranslations("sandboxes");
  const { log, isLoading, error } = useSandboxEvents(connectionId, sessionId);
  const [query, setQuery] = useState("");
  const [operation, setOperation] = useState(ANY);
  const [failedOnly, setFailedOnly] = useState(false);

  // Memoised, or the `?? []` mints a new array on every render and both `useMemo`s
  // below recompute for nothing - which the exhaustive-deps rule is right about.
  const events = useMemo(() => log?.events ?? [], [log]);

  // The operations this log actually holds, rather than every one the service
  // could record: a filter offering `edit` on a sandbox that has only ever been
  // globbed is a filter that answers nothing.
  const operations = useMemo(() => [...new Set(events.map((event) => event.op))].sort(), [events]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (
      [...events]
        // Newest first. The service answers in the order it recorded, so the entry
        // somebody opened this for was at the bottom of a scroll box.
        .reverse()
        .filter((event) => operation === ANY || event.op === operation)
        .filter((event) => !failedOnly || !event.ok)
        .filter(
          (event) =>
            needle === "" ||
            [event.op, event.target, event.detail].some((field) =>
              field.toLowerCase().includes(needle),
            ),
        )
    );
  }, [events, query, operation, failedOnly]);

  const columns = useMemo<Column<SandboxEvent>[]>(
    () => [
      {
        key: "when",
        header: t("sessions.when"),
        className: "pl-5",
        cell: (event) => (
          <span className="text-muted-foreground/70 font-mono text-[10px] whitespace-nowrap">
            {t("sessions.ago", { time: ago(event.at) })}
          </span>
        ),
      },
      {
        key: "outcome",
        header: "",
        cell: (event) =>
          event.ok ? (
            <Check className="text-muted-foreground/40 h-3.5 w-3.5" aria-label={t("sessions.ok")} />
          ) : (
            <X className="text-destructive h-3.5 w-3.5" aria-label={t("sessions.failed")} />
          ),
      },
      {
        key: "op",
        header: t("sessions.operation"),
        cell: (event) => (
          <span className={cn("font-mono text-xs", !event.ok && "text-destructive")}>
            {event.op}
          </span>
        ),
      },
      {
        key: "target",
        header: t("sessions.target"),
        cell: (event) => (
          <span className={cn("font-mono text-xs break-all", !event.ok && "text-destructive")}>
            {event.target}
          </span>
        ),
      },
      {
        key: "detail",
        header: t("sessions.detail"),
        cell: (event) => (
          <span className={cn("text-xs", event.ok ? "text-muted-foreground" : "text-destructive")}>
            {event.detail}
          </span>
        ),
      },
      {
        key: "duration",
        header: t("sessions.duration"),
        align: "right",
        className: "pr-5",
        cell: (event) => (
          <span className="text-muted-foreground text-xs">{`${Math.round(event.duration_ms)}ms`}</span>
        ),
      },
    ],
    [t],
  );

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (log === null || events.length === 0)
    return (
      <p className="text-muted-foreground text-sm">
        {t.rich("nothingRecordedYet", {
          session: sessionId,
          id: (chunks) => <span className="font-mono">{chunks}</span>,
        })}
      </p>
    );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {/* Controls over the log rather than beside the page's own: a sandbox that
          has run three hundred operations is one somebody opened this for a
          reason, and scrolling is not that reason. */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder={t("sessions.searchOperations")}
          className="min-w-48 flex-1"
        />
        <Select value={operation} onValueChange={setOperation}>
          <SelectTrigger className="h-9 w-40" aria-label={t("sessions.operation")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("sessions.anyOperation")}</SelectItem>
            {operations.map((op) => (
              <SelectItem key={op} value={op}>
                {op}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <label className="flex items-center gap-2 text-xs whitespace-nowrap">
          <Switch
            checked={failedOnly}
            onCheckedChange={setFailedOnly}
            aria-label={t("sessions.failedOnly")}
          />
          <span className="text-muted-foreground">{t("sessions.failedOnly")}</span>
        </label>
        <span className="text-muted-foreground/70 ml-auto text-xs whitespace-nowrap">
          {t("sessions.showingOf", { shown: visible.length, total: events.length })}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable<SandboxEvent>
          columns={columns}
          rows={visible}
          getRowKey={(event) => String(event.seq)}
          empty={t("sessions.noOperationMatches")}
        />
      </div>
    </div>
  );
}
