"use client";

import { useTranslations } from "next-intl";

import { useSandboxConnections, useSandboxSessions } from "@/hooks";
import { holdsSessions, tenantShare, watchableConnections } from "@/lib/dashboard/sandbox";
import type { SandboxConnectionRecord } from "@/lib/sandbox-connections-api";
import { MARK_CLASS, QUIET_SURFACE } from "@/lib/dashboard/system";
import { cn } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * How much room this organization has left on each host it runs sandboxes on.
 *
 * The card that answers "why did an agent just get a 429": the host refuses a
 * session once the organization reaches `max_sessions_per_tenant`, and nothing
 * else on the page says so.
 *
 * One figure per connection, and deliberately only one. The host's own ceilings
 * arrive on the same response, but there is no count to put against them - see
 * `lib/dashboard/sandbox.ts` - so they are shown as ceilings by the policy card
 * rather than as a fraction here. A row per connection rather than the default
 * host alone, because the 429 came from whichever one the agent resolved to.
 *
 * Ignores the period filter: every figure here is true only of this moment.
 */
export function SandboxCapacityWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.sandbox-capacity");
  const { connections, isLoading, error, refresh } = useSandboxConnections();
  const hosts = watchableConnections(connections);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error !== null ? (
        <WidgetErrorBody onRetry={() => void refresh()} />
      ) : hosts.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <div className="flex h-full flex-col justify-between gap-3">
          <ul className="space-y-3">
            {hosts.map((host) => (
              <HostCapacity key={host.id} connection={host} />
            ))}
          </ul>
          {/* On screen, not behind the header's info icon like the rest of a
              card's explanation. A reader who is refused a sandbox while this
              card shows room to spare would otherwise have no way to learn that
              the missing figure is missing rather than zero - which is the same
              failure as an unreachable host reading as idle, one level up. */}
          <p className="text-muted-foreground text-xs leading-snug">{t("hostUncounted")}</p>
        </div>
      )}
    </WidgetFrame>
  );
}

/** One host's figure, asked of that host. */
function HostCapacity({ connection }: { connection: SandboxConnectionRecord }) {
  const t = useTranslations("dashboard.widgets.sandbox-capacity");
  // A connection holding none of our sessions is not asked at all: it would
  // answer with the empty list an idle container host answers with.
  const counted = holdsSessions(connection);
  const { listing, error } = useSandboxSessions(counted ? connection.id : null);
  const share = listing === null ? null : tenantShare(listing);

  return (
    <li className="space-y-1.5 text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-foreground truncate font-medium">{connection.name}</span>
        {share !== null ? (
          <span className="text-foreground shrink-0 tabular-nums">
            {share.limit === null
              ? t("openUncapped", { count: share.used })
              : t("openOfTenantLimit", { used: share.used, limit: share.limit })}
          </span>
        ) : null}
      </div>
      {!counted ? (
        <p className="text-muted-foreground">{t("elsewhere")}</p>
      ) : error !== null ? (
        // The host's own sentence, which says whether it is unreachable or its
        // credential was rotated away. Rendering "0 open" for either is the
        // failure #129 calls an empty view and a dead host being the same
        // pixels. No Retry: this query already re-asks every ten seconds.
        <p className="text-destructive">{error}</p>
      ) : share === null ? (
        <WidgetSkeleton rows={1} className="py-0" />
      ) : share.percent !== null ? (
        <CapacityTrack percent={share.percent} />
      ) : null}
    </li>
  );
}

/**
 * The fraction as a bar. Decorative: the same numbers are printed beside it, so
 * colour is never the only channel carrying "this host is nearly full".
 */
function CapacityTrack({ percent }: { percent: number }) {
  return (
    <div className={cn("h-1.5 overflow-hidden rounded-r-sm", QUIET_SURFACE)}>
      <div
        className={cn(
          "h-full rounded-r-sm",
          percent >= 90 ? "bg-destructive" : percent >= 70 ? "bg-warning" : MARK_CLASS,
        )}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
