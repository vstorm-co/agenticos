"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Activity } from "lucide-react";

import { ActivityLog } from "@/components/sandboxes/activity-log";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ListCardControlsRow,
  ListCardEmpty,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  type Column,
} from "@/components/ui";
import { useAgents, useSandboxPolicy, useSandboxSessions } from "@/hooks";
import { primaryConnection } from "@/lib/dashboard/sandbox";
import type { SandboxConnectionRecord, SandboxSession } from "@/lib/sandbox-connections-api";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import { DIALOG_WINDOW } from "@/lib/dialog-sizes";

interface SessionsPanelProps {
  /** The active container connections — the hosts that can be asked at all. */
  connections: SandboxConnectionRecord[];
}

/** Seconds since something happened, as a person reads them. */
function idle(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

/** Bytes as a person reads them, at the scale the number deserves. */
function size(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KiB`;
  if (bytes < 1024 * 1024 * 1024) return `${Math.round(bytes / (1024 * 1024))} MiB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GiB`;
}

/** Bytes against a ceiling, or nothing when the sample was not taken. */
function memory(session: SandboxSession): string {
  const used = session.usage?.memory_bytes;
  if (used === null || used === undefined) return "—";
  const limit = session.usage?.memory_limit_bytes;
  return limit ? `${size(used)} / ${size(limit)}` : size(used);
}

/**
 * How long this sandbox has left before it is reaped, when that is knowable.
 *
 * The number an operator is actually looking for: `29m` idle says nothing on its
 * own, and the ceiling it is measured against is the service's `idle_timeout` -
 * which the page has, because it asks for the policy anyway to name the runtimes.
 * A hibernated sandbox is not counting down: it has already been stopped.
 */
function reapsIn(session: SandboxSession, idleTimeout: number | null): number | null {
  if (idleTimeout === null || !session.alive) return null;
  return Math.max(0, idleTimeout - session.idle_seconds);
}

/** Which agent and chat a sandbox belongs to, in words. */
function belongsTo(session: SandboxSession, t: (key: string) => string): string {
  if (session.scope === null) return t("scopeRun");
  if (session.scope === "conversation") return t("scopeConversation");
  if (session.scope === "channel") return t("scopeChannel");
  if (session.scope === "user") return t("scopeUser");
  return t("scopeAgent");
}

/**
 * What is running on one host, right now.
 *
 * Filtered to this organization by the backend rather than here — one `sandboxd`
 * serves every organization that registered a connection at its address, and a
 * client-side filter would mean the other tenants' containers had already been
 * sent to the browser. The search box below narrows only what that answer
 * already holds.
 *
 * Memory and CPU are opt-in because the service samples each sandbox
 * individually for them: a page that shows twenty should not pay twenty daemon
 * round trips to load.
 */
export function SessionsPanel({ connections }: SessionsPanelProps) {
  const t = useTranslations("sandboxes.sessions");
  const [usage, setUsage] = useState(false);
  const [watching, setWatching] = useState<string | null>(null);
  const [chosenId, setChosenId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  // The chosen host, defaulting to the connection an agent that names none
  // gets — but saying which one it is, and offering the rest, rather than
  // silently showing one of three (#140).
  const connection =
    connections.find((entry) => entry.id === chosenId) ?? primaryConnection(connections);

  const { listing, isLoading, error } = useSandboxSessions(connection?.id ?? null, usage);
  // Asked for the same reason the runtimes are: the ceilings in force are what
  // turn `29m` into `reaped in 1m`. One request per host, on a page an operator
  // opened to ask exactly that.
  const { policy } = useSandboxPolicy(connection?.id ?? null);
  // Names for the ids the host answers with. It knows the agent that opened each
  // sandbox and nothing about what that agent is called.
  const { agents } = useAgents();
  const nameOf = useMemo(() => {
    const byId = new Map(agents.map((agent) => [agent.id, agent.name]));
    return (session: SandboxSession) =>
      session.agent_id === null ? null : (byId.get(session.agent_id) ?? null);
  }, [agents]);

  const watched = useMemo(
    () => (listing?.sessions ?? []).find((session) => session.session_id === watching) ?? null,
    [listing, watching],
  );

  const visible = useMemo(() => {
    const sessions = listing?.sessions ?? [];
    const needle = query.trim().toLowerCase();
    if (!needle) return sessions;
    return sessions.filter((session) =>
      [session.session_id, session.runtime, session.state].some((field) =>
        field.toLowerCase().includes(needle),
      ),
    );
  }, [listing, query]);

  const columns = useMemo<Column<SandboxSession>[]>(
    () => [
      {
        key: "session",
        className: "pl-5",
        header: t("session"),
        sortable: true,
        sortValue: (session) => nameOf(session) ?? session.session_id,
        // The agent, with the key underneath. A column of
        // `xc-40bfd3cc-ca1b1445-d9bdc4992aba470eb26e8716d3c77aaa` answers no
        // question anybody brought to this page: whose sandbox is this, and may
        // I close it. The id stays because it is what the service is asked with.
        cell: (session) => (
          <span className="flex min-w-0 flex-col">
            <span className="text-foreground text-xs font-medium">
              {nameOf(session) ?? t("anAgent")}
            </span>
            <span className="text-muted-foreground/70 truncate font-mono text-[10px]">
              {session.session_id}
            </span>
          </span>
        ),
      },
      {
        key: "runtime",
        header: t("runtime"),
        cell: (session) => <span className="text-muted-foreground text-xs">{session.runtime}</span>,
      },
      {
        key: "sharedBy",
        header: t("sharedBy"),
        // A link where there is one to give. "one conversation" is the scope; the
        // conversation itself is the thing an operator wants when a sandbox is
        // holding memory they cannot account for.
        // A link only where it leads somewhere: the chat page lists its owner's
        // threads, so one to anybody else's lands on an empty sidebar dressed as
        // the conversation - and this listing is organization-wide, which made
        // that most of the column. The same test the workspace table applies.
        cell: (session) =>
          session.conversation_id === null || !session.conversation_is_callers ? (
            <span className="text-muted-foreground text-xs">{belongsTo(session, t)}</span>
          ) : (
            <Link
              href={`/chat?id=${session.conversation_id}`}
              className="text-muted-foreground hover:text-foreground text-xs underline decoration-dotted"
            >
              {belongsTo(session, t)}
            </Link>
          ),
      },
      {
        key: "state",
        header: t("state"),
        cell: (session) => (
          // Hibernated is not dead: the sandbox was stopped to free a slot and its
          // files and log are still there. Said in words on hover, because the
          // state name alone reads as a failure to anybody who has not read the
          // service's documentation (#1039).
          <Badge
            variant={session.alive ? "secondary" : "outline"}
            title={session.alive ? t("stateRunningMeans") : t("stateHibernatedMeans")}
          >
            {session.state}
          </Badge>
        ),
      },
      {
        key: "idle",
        header: t("idle"),
        sortable: true,
        sortValue: (session) => session.idle_seconds,
        cell: (session) => {
          const left = reapsIn(session, policy?.idle_timeout ?? null);
          return (
            <span className="flex flex-col">
              <span className="text-muted-foreground text-xs">{idle(session.idle_seconds)}</span>
              {left !== null && (
                <span
                  className={cn(
                    "text-[10px]",
                    left < 120 ? "text-amber-600" : "text-muted-foreground/70",
                  )}
                >
                  {t("reapedIn", { time: idle(left) })}
                </span>
              )}
            </span>
          );
        },
      },
      {
        key: "memory",
        header: t("memory"),
        sortable: true,
        sortValue: (session) => session.usage?.memory_bytes ?? null,
        cell: (session) => <span className="text-muted-foreground text-xs">{memory(session)}</span>,
      },
      {
        key: "activity",
        className: "pr-5",
        header: t("activity"),
        align: "right",
        cell: (session) => (
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("activityOf", { id: session.session_id })}
            // Opens only. The log is a modal, so while one is open its row is
            // behind it and out of the accessibility tree - a second label on this
            // button would be one nothing can read and nothing can press.
            onClick={() => setWatching(session.session_id)}
          >
            {t("show")}
          </Button>
        ),
      },
    ],
    [t, nameOf, policy],
  );

  if (connection === null)
    return (
      <Card>
        <CardContent className="p-0">
          <ListCardEmpty
            icon={Activity}
            title={t("noContainerConnection")}
            description={t("noContainerConnectionHint")}
          />
        </CardContent>
      </Card>
    );

  const sessions = listing?.sessions ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4" aria-hidden />
            {t("runningOn", { name: connection.name })}
          </CardTitle>
          <CardDescription className="text-xs">
            {listing?.tenant_limit
              ? t("sessionsOfLimit", { count: sessions.length, limit: listing.tenant_limit })
              : t("sessionsCount", { count: sessions.length })}
          </CardDescription>
        </div>
        <div className="flex items-center gap-4">
          {connections.length > 1 && (
            <Select
              value={connection.id}
              // A session id names a sandbox on one host, so an activity log
              // left open would ask the new host for the old host's session.
              onValueChange={(id) => {
                setChosenId(id);
                setWatching(null);
              }}
            >
              <SelectTrigger className="h-8 w-44" aria-label={t("host")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {connections.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <label className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">{t("sampleMemory")}</span>
            <Switch
              checked={usage}
              onCheckedChange={setUsage}
              aria-label={t("sampleMemoryAndCpu")}
            />
          </label>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <ListCardControlsRow>
          <SearchInput value={query} onChange={setQuery} placeholder={t("searchSessions")} />
        </ListCardControlsRow>
        {/* What this table is, once, where somebody who opened the tab is looking.
            "Nothing running" and "nothing configured" are the same empty grid, and
            a session opening on the first tool call rather than when a chat starts
            is the part nobody guesses (#1039). */}
        <p className="text-muted-foreground border-border border-t px-5 py-2 text-xs">
          {t("whatSessionsAre")}
        </p>
        <DataTable<SandboxSession>
          columns={columns}
          rows={visible}
          getRowKey={(session) => session.session_id}
          loading={isLoading}
          error={
            error === null ? undefined : (
              <span className="inline-flex items-start gap-2 text-left">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                {error}
              </span>
            )
          }
          empty={sessions.length === 0 ? t("nothingRunningSandboxOpens") : t("noSessionMatches")}
          className="rounded-none border-0 bg-transparent"
        />

        {/* A dialog rather than a panel under the table. Expanded in place, the log
            was a table inside a table - its columns lining up with none of the
            ones above them, its scroll box competing with the page's, and the row
            it belonged to pushed out of sight by it. It is also the one thing on
            this page somebody reads rather than scans, which is what a dialog is
            for. */}
        <Dialog open={watching !== null} onOpenChange={(open) => !open && setWatching(null)}>
          {/* The same shape as the file viewer, for the same reason: this is a log
              with five columns and three hundred rows, read rather than glanced at,
              and a `max-w-3xl` box turned every target into an ellipsis. */}
          <DialogContent className={DIALOG_WINDOW}>
            <DialogHeader className="gap-1 pr-8">
              <DialogTitle className="text-base">
                {watched === null
                  ? t("activity")
                  : t("activityOfAgent", { name: nameOf(watched) ?? t("anAgent") })}
              </DialogTitle>
              {/* What the service records, and what it does not. The distinction is
                  the reason this log can be shown to anybody who can see the page:
                  it audits what was done, and is not a way to read the work. */}
              <DialogDescription className="text-xs">{t("whatIsRecorded")}</DialogDescription>
              {watching !== null && (
                <p className="text-muted-foreground/70 truncate font-mono text-[10px]">
                  {watching}
                </p>
              )}
            </DialogHeader>
            <div className="min-h-0 flex-1 overflow-auto">
              {watching !== null && <ActivityLog sessionId={watching} />}
            </div>
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
