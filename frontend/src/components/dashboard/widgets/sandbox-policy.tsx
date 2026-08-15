"use client";

import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { useSandboxConnections, useSandboxPolicy } from "@/hooks";
import { holdsSessions, primaryConnection } from "@/lib/dashboard/sandbox";
import type { SandboxPolicy } from "@/lib/sandbox-connections-api";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * What the host allows: the runtimes an agent may ask for, and the ceilings.
 *
 * Read-only by design rather than by omission. These are `sandboxd`'s own boot
 * configuration, and an endpoint letting a browser change them would be an
 * endpoint that reconfigures the process holding the Docker socket. They are here
 * so that what is in force is *visible* - an operator whose agents keep dying on
 * a memory limit has somewhere to look.
 *
 * This is also where `max_sessions` and `max_open_sessions` belong. They are
 * ceilings for every organization on the host, so there is no count of ours to
 * put against them; naming them host-wide is the honest rendering, and the
 * capacity card draws the one fraction that does divide cleanly.
 */
export function SandboxPolicyWidget({ title, hint, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.sandbox-policy");
  const { connections, isLoading, error, refresh } = useSandboxConnections();
  const host = primaryConnection(connections);
  // Daytona publishes no allowlist of its own, so it is not asked: what it
  // permits is an account setting on their side.
  const asked = host !== null && holdsSessions(host) ? host.id : null;
  const policy = useSandboxPolicy(asked);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error !== null ? (
        <WidgetErrorBody onRetry={() => void refresh()} />
      ) : host === null ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : asked === null ? (
        <WidgetEmptyBody title={t("elsewhere.title")} description={t("elsewhere.description")} />
      ) : policy.error !== null ? (
        <WidgetErrorBody onRetry={policy.refetch} />
      ) : policy.policy === null ? (
        // Still being asked. `policy.isLoading` is deliberately not read: the
        // absent answer is the same condition, and two ways to spell it leaves
        // one of them unreachable.
        <WidgetSkeleton />
      ) : (
        <PolicyBody policy={policy.policy} />
      )}
    </WidgetFrame>
  );
}

/** Which ceilings this service publishes, in the order a reader needs them. */
function ceilingsOf(policy: SandboxPolicy): { key: string; value: number }[] {
  return [
    { key: "perOrganization", value: policy.max_sessions_per_tenant },
    { key: "hostResident", value: policy.max_sessions },
    { key: "hostOpen", value: policy.max_open_sessions },
  ].filter((row): row is { key: string; value: number } => row.value !== null);
}

function PolicyBody({ policy }: { policy: SandboxPolicy }) {
  const t = useTranslations("dashboard.widgets.sandbox-policy");
  const ceilings = ceilingsOf(policy);

  return (
    <div className="flex h-full flex-col gap-3">
      {ceilings.length > 0 ? (
        <dl className="grid grid-cols-3 gap-x-3 text-xs">
          {ceilings.map((row) => (
            <div key={row.key}>
              <dt className="text-muted-foreground truncate">{t(`ceilings.${row.key}`)}</dt>
              <dd className="text-foreground font-medium tabular-nums">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {policy.runtimes.length === 0 ? (
        // Not an empty state: a service allowing no runtime is a service on which
        // no agent can run code at all.
        <p className="text-destructive text-xs">{t("noRuntime")}</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-1.5 overflow-auto">
          {policy.runtimes.map((runtime) => (
            <li key={runtime.alias} className="flex items-center gap-2 text-xs">
              <span className="text-foreground shrink-0 font-mono">{runtime.alias}</span>
              {runtime.alias === policy.default_runtime ? (
                <Badge variant="secondary" className="shrink-0">
                  {t("default")}
                </Badge>
              ) : null}
              <span className="text-muted-foreground min-w-0 flex-1 truncate">
                {runtime.description}
              </span>
              <span className="text-foreground shrink-0 tabular-nums">
                {runtime.mem_limit ?? t("noMemoryCeiling")}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
