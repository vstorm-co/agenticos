"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, Button, Switch } from "@/components/ui";
import { useAgents, useSandboxConnections, useSandboxSessions } from "@/hooks";
import {
  holdsSessions,
  idleLabel,
  memoryLabel,
  primaryConnection,
  scopeKey,
} from "@/lib/dashboard/sandbox";
import type { SandboxConnectionRecord, SandboxSession } from "@/lib/sandbox-connections-api";
import { SandboxActivity } from "./sandbox-activity";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Every sandbox this organization has open on the host its agents resolve to.
 *
 * The default connection, not all of them: capacity is the card that covers
 * every host, and a dashboard card cannot be a table across several. Its "see
 * all" is the Sandboxes page, which is where the rest of them live.
 *
 * Memory and CPU are behind the switch because the service samples each sandbox
 * individually for them - a card listing twenty would otherwise buy twenty daemon
 * round trips on load, every ten seconds. The listing arrives already filtered to
 * this organization, so nothing here filters it again.
 *
 * Ignores the period filter: a sandbox is either open now or it is not.
 */
export function SandboxSessionsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.sandbox-sessions");
  const [usage, setUsage] = useState(false);
  const { connections, isLoading, error, refresh } = useSandboxConnections();
  const host = primaryConnection(connections);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error !== null ? (
        <WidgetErrorBody onRetry={() => void refresh()} />
      ) : host === null ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : !holdsSessions(host) ? (
        <WidgetEmptyBody title={t("elsewhere.title")} description={t("elsewhere.description")} />
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-3">
          <div className="flex items-center justify-between gap-2 text-xs">
            <p className="text-muted-foreground truncate">{t("runningOn", { name: host.name })}</p>
            <label className="flex shrink-0 items-center gap-2">
              <span className="text-muted-foreground">{t("sampleUsage")}</span>
              <Switch
                checked={usage}
                onCheckedChange={setUsage}
                aria-label={t("sampleUsageHint")}
              />
            </label>
          </div>
          <HostSessions connection={host} usage={usage} />
        </div>
      )}
    </WidgetFrame>
  );
}

/** One host's open sandboxes, asked of that host. */
function HostSessions({
  connection,
  usage,
}: {
  connection: SandboxConnectionRecord;
  usage: boolean;
}) {
  const t = useTranslations("dashboard.widgets.sandbox-sessions");
  const [watching, setWatching] = useState<string | null>(null);
  const { listing, error } = useSandboxSessions(connection.id, usage);
  const { agents } = useAgents();
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));

  // The host's own sentence rather than an empty list: it says whether nothing is
  // running, the service is unreachable, or its credential was rotated away.
  if (error !== null) return <p className="text-destructive text-xs">{error}</p>;
  if (listing === null) return <WidgetSkeleton rows={3} />;
  if (listing.sessions.length === 0)
    return <p className="text-muted-foreground text-xs">{t("nothingRunning")}</p>;

  return (
    <ul className="min-h-0 flex-1 space-y-2.5 overflow-auto">
      {listing.sessions.map((session) => (
        <SessionRow
          key={session.session_id}
          connectionId={connection.id}
          session={session}
          agentName={session.agent_id === null ? undefined : names.get(session.agent_id)}
          watching={watching === session.session_id}
          onToggle={() => setWatching(watching === session.session_id ? null : session.session_id)}
        />
      ))}
    </ul>
  );
}

interface SessionRowProps {
  connectionId: string;
  session: SandboxSession;
  /** Absent for a `run`-scoped sandbox, which has no workspace row to join. */
  agentName?: string;
  watching: boolean;
  onToggle: () => void;
}

function SessionRow({ connectionId, session, agentName, watching, onToggle }: SessionRowProps) {
  const t = useTranslations("dashboard.widgets.sandbox-sessions");
  const idle = idleLabel(session.idle_seconds);
  const memory = memoryLabel(session);

  return (
    <li className="space-y-1.5">
      <div className="flex items-center gap-2 text-xs">
        {/* Hibernated is not dead: the sandbox was stopped to free a slot, and
            its files and its log are both still there. */}
        <Badge variant={session.alive ? "secondary" : "outline"} className="shrink-0">
          {session.state}
        </Badge>
        <span className="min-w-0 flex-1">
          <span className="text-foreground block truncate">{agentName ?? t("unattributed")}</span>
          <span className="text-muted-foreground block truncate">{t(scopeKey(session.scope))}</span>
        </span>
        <span className="text-muted-foreground shrink-0 font-mono">{session.runtime}</span>
        <span className="text-muted-foreground shrink-0 tabular-nums">
          {t(idle.key, { count: idle.count })}
        </span>
        {memory !== null ? (
          <span className="text-foreground shrink-0 tabular-nums">
            {memory.limit === null
              ? memory.used
              : t("memoryOfLimit", { used: memory.used, limit: memory.limit })}
          </span>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0"
          aria-label={t("activityOf", { id: session.session_id })}
          onClick={onToggle}
        >
          {watching ? t("hideActivity") : t("showActivity")}
        </Button>
      </div>
      {watching ? (
        <SandboxActivity connectionId={connectionId} sessionId={session.session_id} />
      ) : null}
    </li>
  );
}
