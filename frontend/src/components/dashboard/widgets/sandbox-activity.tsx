"use client";

import { useTranslations } from "next-intl";

import { useSandboxEvents } from "@/hooks";
import { cn } from "@/lib/utils";
import { WidgetSkeleton } from "../widget-states";

/**
 * What was done inside one sandbox: paths read, commands run, how each went.
 *
 * Not a card of its own, and it could not be one - `DashboardWidgetProps` carries
 * no session and the events route takes one. A feed across every open sandbox
 * would be a request per sandbox on load, which is the cost `usage=true` is
 * opt-in to avoid. So it hangs off the row whose log it is.
 *
 * Paths and commands, never their contents or their output: the service records
 * neither, which is what keeps this an audit of an agent's work rather than a way
 * to read it.
 */
export function SandboxActivity({
  connectionId,
  sessionId,
}: {
  connectionId: string;
  sessionId: string;
}) {
  const t = useTranslations("dashboard.widgets.sandbox-sessions");
  const { log, error } = useSandboxEvents(connectionId, sessionId);

  if (error !== null) return <p className="text-destructive text-xs">{error}</p>;
  if (log === null) return <WidgetSkeleton rows={2} className="py-0" />;
  if (log.events.length === 0)
    return <p className="text-muted-foreground text-xs">{t("noActivity")}</p>;

  return (
    <ul className="bg-muted max-h-40 space-y-1 overflow-auto rounded-md p-2">
      {log.events.map((event) => (
        <li
          key={event.seq}
          className={cn("flex items-baseline gap-2 text-xs", !event.ok && "text-destructive")}
        >
          <span className="shrink-0 font-mono">{event.op}</span>
          <span className="text-muted-foreground min-w-0 flex-1 truncate font-mono">
            {event.target}
          </span>
          <span className="text-muted-foreground shrink-0 tabular-nums">
            {t("tookMs", { ms: Math.round(event.duration_ms) })}
          </span>
        </li>
      ))}
    </ul>
  );
}
