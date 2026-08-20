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
import { useSandboxSessions } from "@/hooks";
import { primaryConnection } from "@/lib/dashboard/sandbox";
import type { SandboxConnectionRecord, SandboxSession } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

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

/** Bytes against a ceiling, or nothing when the sample was not taken. */
function memory(session: SandboxSession): string {
  const used = session.usage?.memory_bytes;
  if (used === null || used === undefined) return "—";
  const limit = session.usage?.memory_limit_bytes;
  const mib = (value: number) => `${Math.round(value / (1024 * 1024))} MiB`;
  return limit ? `${mib(used)} / ${mib(limit)}` : mib(used);
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
        sortValue: (session) => session.session_id,
        cell: (session) => <span className="font-mono text-xs">{session.session_id}</span>,
      },
      {
        key: "runtime",
        header: t("runtime"),
        cell: (session) => <span className="text-muted-foreground text-xs">{session.runtime}</span>,
      },
      {
        key: "sharedBy",
        header: t("sharedBy"),
        cell: (session) => (
          <span className="text-muted-foreground text-xs">{belongsTo(session, t)}</span>
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
        cell: (session) => (
          <span className="text-muted-foreground text-xs">{idle(session.idle_seconds)}</span>
        ),
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
            onClick={() => setWatching(watching === session.session_id ? null : session.session_id)}
          >
            {watching === session.session_id ? t("hide2") : t("show")}
          </Button>
        ),
      },
    ],
    [t, watching],
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

        {watching !== null && (
          <div className="px-5 py-4">
            <ActivityLog connectionId={connection.id} sessionId={watching} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
