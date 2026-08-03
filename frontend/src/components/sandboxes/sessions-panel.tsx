"use client";

import { useState } from "react";
import { AlertTriangle, Activity } from "lucide-react";

import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Skeleton,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui";
import { useSandboxEvents, useSandboxSessions } from "@/hooks";
import type { SandboxConnectionRecord, SandboxSession } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface SessionsPanelProps {
  /** The connection to watch, or `null` for a deployment with none registered. */
  connection: SandboxConnectionRecord | null;
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
function belongsTo(session: SandboxSession): string {
  if (session.scope === null) return "a single run";
  if (session.scope === "conversation") return "one conversation";
  if (session.scope === "channel") return "one channel";
  if (session.scope === "user") return "one person";
  return "the whole agent";
}

/**
 * What is running on one host, right now.
 *
 * Filtered to this organization by the backend rather than here — one `sandboxd`
 * serves every organization that registered a connection at its address, and a
 * client-side filter would mean the other tenants' containers had already been
 * sent to the browser.
 *
 * Memory and CPU are opt-in because the service samples each sandbox
 * individually for them: a page that shows twenty should not pay twenty daemon
 * round trips to load.
 */
export function SessionsPanel({ connection }: SessionsPanelProps) {
  const t = useTranslations("sandboxes.sessions");
  const [usage, setUsage] = useState(false);
  const [watching, setWatching] = useState<string | null>(null);
  const { listing, isLoading, error } = useSandboxSessions(connection?.id ?? null, usage);

  if (connection === null) return null;

  const sessions = listing?.sessions ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2 text-sm">
            <Activity className="h-4 w-4" aria-hidden />
            Running on {connection.name}
          </CardTitle>
          <CardDescription className="text-xs">
            {sessions.length} of this organization&apos;s sandboxes
            {listing?.tenant_limit ? `, out of ${listing.tenant_limit} allowed` : ""}. Refreshed
            every ten seconds.
          </CardDescription>
        </div>
        <label className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">{t("sampleMemory")}</span>
          <Switch checked={usage} onCheckedChange={setUsage} aria-label={t("sampleMemoryAndCpu")} />
        </label>
      </CardHeader>
      <CardContent className="space-y-3 p-5">
        {isLoading && <Skeleton className="h-20 w-full" />}

        {error !== null && (
          <div className="text-destructive flex items-start gap-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p>{error}</p>
          </div>
        )}

        {error === null && !isLoading && sessions.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("nothingRunningSandboxOpens")}</p>
        )}

        {sessions.length > 0 && (
          <div className="overflow-x-auto px-5 pb-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("session")}</TableHead>
                  <TableHead>{t("runtime")}</TableHead>
                  <TableHead>{t("sharedBy")}</TableHead>
                  <TableHead>{t("state")}</TableHead>
                  <TableHead>{t("idle")}</TableHead>
                  <TableHead>{t("memory")}</TableHead>
                  <TableHead className="text-right">{t("activity")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.map((session) => (
                  <TableRow key={session.session_id}>
                    <TableCell className="font-mono text-xs">{session.session_id}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {session.runtime}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {belongsTo(session)}
                    </TableCell>
                    <TableCell>
                      {/* Hibernated is not dead: the sandbox was stopped to free
                          a slot and its files and log are still there. */}
                      <Badge variant={session.alive ? "secondary" : "outline"}>
                        {session.state}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {idle(session.idle_seconds)}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {memory(session)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Activity of ${session.session_id}`}
                        onClick={() =>
                          setWatching(watching === session.session_id ? null : session.session_id)
                        }
                      >
                        {watching === session.session_id ? "Hide" : "Show"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}

        {watching !== null && <ActivityLog connectionId={connection.id} sessionId={watching} />}
      </CardContent>
    </Card>
  );
}

interface ActivityLogProps {
  connectionId: string;
  sessionId: string;
}

/**
 * What was done to one sandbox.
 *
 * Paths and commands, never their contents or output — the service does not
 * record those, which is what keeps this from becoming a way to read an agent's
 * work rather than audit it.
 */
function ActivityLog({ connectionId, sessionId }: ActivityLogProps) {
  const t = useTranslations("sandboxes");
  const { log, isLoading, error } = useSandboxEvents(connectionId, sessionId);

  if (isLoading) return <Skeleton className="h-24 w-full" />;
  if (error !== null) return <p className="text-destructive text-sm">{error}</p>;
  if (log === null || log.events.length === 0)
    return (
      <p className="text-muted-foreground text-sm">
        Nothing recorded for <span className="font-mono">{sessionId}</span>
        {t("yet")}
      </p>
    );

  return (
    <div className="bg-muted max-h-64 overflow-auto rounded-md p-3">
      <table className="w-full text-xs">
        <tbody>
          {log.events.map((event) => (
            <tr key={event.seq} className={event.ok ? "" : "text-destructive"}>
              <td className="pr-3 font-mono">{event.op}</td>
              <td className="pr-3 font-mono break-all">{event.target}</td>
              <td className="text-muted-foreground pr-3">{event.detail}</td>
              <td className="text-muted-foreground text-right">
                {Math.round(event.duration_ms)}ms
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
