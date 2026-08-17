"use client";

import { useMemo } from "react";
import { AlertTriangle } from "lucide-react";

import {
  Badge,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Skeleton,
  type Column,
} from "@/components/ui";
import { useSandboxPolicy } from "@/hooks";
import type { SandboxConnectionRecord, SandboxRuntime } from "@/lib/sandbox-connections-api";
import { useTranslations } from "next-intl";

interface PolicyPanelProps {
  /** The connection to ask, or `null` while the panel is closed. */
  connection: SandboxConnectionRecord | null;
  onOpenChange: (open: boolean) => void;
}

/** Seconds, as a person reads them. */
function timeout(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds % 60 === 0) return `${seconds / 60} min`;
  return `${seconds}s`;
}

/**
 * What a connection's service allows, read from the service.
 *
 * Read-only, and that is a design decision rather than an unfinished screen. The
 * runtime allowlist and the ceilings behind each alias are the service's own boot
 * configuration; an endpoint that let a browser change them would be an endpoint
 * that reconfigures the process holding the Docker socket. They are shown here so
 * that what is in force is *visible* - an operator whose agents keep hitting a
 * memory limit has somewhere to look - and changed where it can be done safely,
 * in the service's own environment.
 */
export function PolicyPanel({ connection, onOpenChange }: PolicyPanelProps) {
  const t = useTranslations("sandboxes.policy");
  const { policy, isLoading, error } = useSandboxPolicy(connection?.id ?? null);

  const defaultRuntime = policy?.default_runtime ?? null;
  const columns = useMemo<Column<SandboxRuntime>[]>(
    () => [
      {
        key: "alias",
        header: t("alias"),
        cell: (runtime) => (
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs">{runtime.alias}</span>
            {runtime.alias === defaultRuntime && <Badge variant="secondary">{t("default")}</Badge>}
          </div>
        ),
      },
      {
        key: "image",
        header: t("image"),
        cell: (runtime) => (
          <span className="text-muted-foreground font-mono text-xs">
            {runtime.image ?? (runtime.builds ? t("builtHost") : "—")}
          </span>
        ),
      },
      {
        key: "memory",
        header: t("memory"),
        cell: (runtime) => (
          <span className="text-muted-foreground text-xs">{runtime.mem_limit ?? "—"}</span>
        ),
      },
      {
        key: "cpus",
        header: t("cpus"),
        cell: (runtime) => (
          <span className="text-muted-foreground text-xs">{runtime.cpus ?? "—"}</span>
        ),
      },
      {
        key: "network",
        header: t("network"),
        cell: (runtime) => (
          <span className="text-muted-foreground text-xs">{runtime.network_mode ?? "—"}</span>
        ),
      },
    ],
    [t, defaultRuntime],
  );

  return (
    <Dialog open={connection !== null} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("whatConnectionAllows", { name: connection?.name ?? "" })}</DialogTitle>
          <DialogDescription>{t("readFromServiceItself")}</DialogDescription>
        </DialogHeader>

        {isLoading && <Skeleton className="h-32 w-full" />}

        {error !== null && (
          <div className="text-destructive flex items-start gap-2 text-sm">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p>{t("errorUntilItAnswers", { error })}</p>
          </div>
        )}

        {policy !== null && (
          <div className="space-y-4">
            {/* Each one names the variable that sets it. "Idle timeout: 30 min"
                with no way to change it and nothing saying where it comes from
                reads as a limit this application chose; it is the service's own
                boot configuration, and naming the variable is the difference
                between a dead end and a one-line edit in a compose file. */}
            <dl className="text-muted-foreground grid gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
              <div>
                <dt>{t("perOrganization")}</dt>
                <dd className="text-foreground font-medium">
                  {policy.max_sessions_per_tenant ?? "—"}
                </dd>
                <dd className="font-mono text-[10px]">{t("sandboxdMaxSessionsPer")}</dd>
              </div>
              <div>
                <dt>{t("idleTimeout")}</dt>
                <dd className="text-foreground font-medium">{timeout(policy.idle_timeout)}</dd>
                <dd className="font-mono text-[10px]">{t("sandboxdIdleTimeout")}</dd>
              </div>
              <div>
                <dt>{t("keptBetweenTurns")}</dt>
                <dd className="text-foreground font-medium">
                  {policy.persist_containers === false ? "no" : "yes"}
                </dd>
                <dd className="font-mono text-[10px]">{t("sandboxdPersistContainers")}</dd>
              </div>
            </dl>

            <p className="text-muted-foreground text-xs">
              {t.rich("serviceEnvironmentDescription", {
                service: t("sandboxd"),
                mono: (chunks) => <span className="font-mono">{chunks}</span>,
              })}
            </p>

            {policy.runtimes.length === 0 ? (
              <p className="text-destructive text-sm">{t("serviceAllowsNoRuntime")}</p>
            ) : (
              <DataTable<SandboxRuntime>
                columns={columns}
                rows={policy.runtimes}
                getRowKey={(runtime) => runtime.alias}
              />
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
