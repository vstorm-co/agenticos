"use client";

import { useMemo, useState } from "react";

import {
  DataTable,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  Switch,
  useDebounced,
  type Column,
} from "@/components/ui";
import { useSandboxOperations } from "@/hooks";
import type { SandboxOperation } from "@/lib/sandbox-connections-api";
import { Check, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

/** The "no filter" value. A `Select` cannot hold `""`, but it can hold this. */
const ANY = "__any__";

const PAGE = 50;

/**
 * How long ago, compactly.
 *
 * Not `timeAgo` from `lib/utils`: that one writes prose ("3 minutes ago") for a
 * sentence, and this is a 10px monospace column beside two hundred rows. The clock
 * is read here rather than during render for the same reason `timeAgo` is shaped
 * that way - `Date.now()` in a component is impure and the React rule refuses it.
 */
function ago(at: string): string {
  const then = new Date(at).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

interface ActivityLogProps {
  sessionId: string;
}

/**
 * What was done to one sandbox.
 *
 * **Read from this platform's own record, not the service's.** The service keeps a
 * 200-entry ring buffer in its process memory and its `after` parameter is a
 * polling cursor rather than a page, so what it dropped could not be asked for, a
 * conversation worked in all day had lost its morning, and restarting `sandboxd`
 * lost every log on the host (#1061). These rows answer a week later.
 *
 * Which is also what makes the controls mean something: the search, the operation
 * filter and the failed-only switch narrow a **query**, and the pager pages a
 * result set with a real total - where before they filtered an array the client
 * already held and the pager had nothing to page to.
 *
 * Paths and commands, never their contents or output. That is what keeps the log an
 * audit rather than a way to read an agent's work, and it is the sentence below the
 * table.
 *
 * One thing the service's buffer still did better: it showed a call the moment it
 * happened. These rows are written into the run's own transaction, so a turn's
 * operations arrive together when the turn commits - a second or so after it ends.
 */
export function ActivityLog({ sessionId }: ActivityLogProps) {
  const t = useTranslations("sandboxes");
  const [query, setQuery] = useState("");
  const [operation, setOperation] = useState(ANY);
  const [failedOnly, setFailedOnly] = useState(false);
  const [page, setPage] = useState(0);

  // Every control resets the page: filtering to nine rows while sitting on page
  // four is an empty table that reads as "nothing matches".
  function narrow(change: () => void) {
    change();
    setPage(0);
  }

  // Debounced, because the search is a request rather than a filter over an array
  // the client holds: a round trip per keystroke can also land out of order.
  const settled = useDebounced(query.trim());

  const { log, error } = useSandboxOperations({
    sessionKey: sessionId,
    op: operation === ANY ? null : operation,
    failedOnly,
    query: settled,
    skip: page * PAGE,
    limit: PAGE,
  });

  const columns = useMemo<Column<SandboxOperation>[]>(
    () => [
      {
        key: "when",
        header: t("sessions.when"),
        className: "pl-5",
        cell: (row) => (
          <span className="text-muted-foreground/70 font-mono text-[10px] whitespace-nowrap">
            {t("sessions.ago", { time: ago(row.at) })}
          </span>
        ),
      },
      {
        key: "outcome",
        header: "",
        cell: (row) =>
          row.ok ? (
            <Check className="text-muted-foreground/40 h-3.5 w-3.5" aria-label={t("sessions.ok")} />
          ) : (
            <X className="text-destructive h-3.5 w-3.5" aria-label={t("sessions.failed")} />
          ),
      },
      {
        key: "op",
        header: t("sessions.operation"),
        cell: (row) => (
          <span className={cn("font-mono text-xs", !row.ok && "text-destructive")}>{row.op}</span>
        ),
      },
      {
        key: "target",
        header: t("sessions.target"),
        cell: (row) => (
          <span className={cn("font-mono text-xs break-all", !row.ok && "text-destructive")}>
            {row.target}
          </span>
        ),
      },
      {
        // The two facts the service's own log could never carry, and the two
        // somebody auditing a sandbox actually came for.
        key: "agent",
        header: t("sessions.byAgent"),
        cell: (row) => (
          <span className="text-muted-foreground text-xs">
            {row.agent_name ?? t("sessions.agentGone")}
          </span>
        ),
      },
      {
        key: "detail",
        header: t("sessions.detail"),
        cell: (row) => (
          <span className={cn("text-xs", row.ok ? "text-muted-foreground" : "text-destructive")}>
            {row.detail}
          </span>
        ),
      },
      {
        key: "duration",
        header: t("sessions.duration"),
        align: "right",
        className: "pr-5",
        cell: (row) => (
          <span className="text-muted-foreground text-xs">{`${row.duration_ms}ms`}</span>
        ),
      },
    ],
    [t],
  );

  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  // A null log is the first fetch and nothing else: paging keeps the previous page
  // on screen, so a later request never empties this. Reading it before the
  // filters is also what keeps the three fields below from needing fallbacks that
  // nothing could ever reach.
  if (log === null) return <Skeleton className="h-24 w-full" />;

  const { items, total, operations } = log;
  const filtered = settled !== "" || operation !== ANY || failedOnly;

  // Nothing recorded *and* nothing asked for: the sandbox has done nothing yet, or
  // has done it before this record existed. Distinct from a filter matching none,
  // which is the table's own empty line.
  if (total === 0 && !filtered)
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
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onChange={(next) => narrow(() => setQuery(next))}
          placeholder={t("sessions.searchOperations")}
          className="min-w-48 flex-1"
        />
        <Select value={operation} onValueChange={(next) => narrow(() => setOperation(next))}>
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
            onCheckedChange={(next) => narrow(() => setFailedOnly(next))}
            aria-label={t("sessions.failedOnly")}
          />
          <span className="text-muted-foreground">{t("sessions.failedOnly")}</span>
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <DataTable<SandboxOperation>
          columns={columns}
          rows={items}
          getRowKey={(row) => row.id}
          empty={t("sessions.noOperationMatches")}
        />
      </div>

      <Pager
        page={page}
        pageCount={Math.max(1, Math.ceil(total / PAGE))}
        matched={total}
        total={total}
        onPage={setPage}
        counted={t("sessions.operationCount", { count: total })}
      />
    </div>
  );
}
