"use client";

import { AlertTriangle } from "lucide-react";

import {
  Badge,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Skeleton,
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
 * One measured fact, in the shape both halves of this dialog use.
 *
 * A label above its value, and a third line naming where the value comes from.
 * The same component for a runtime's memory ceiling and for the service's idle
 * timeout, because they are the same kind of thing to the person reading: a
 * number in force, and somewhere to go and change it.
 */
function Fact({ label, value, source }: { label: string; value: string; source?: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="text-foreground truncate text-sm font-medium">{value}</dd>
      {source !== undefined && (
        <dd className="text-muted-foreground/70 truncate font-mono text-[10px]">{source}</dd>
      )}
    </div>
  );
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
 *
 * **The runtimes come first, and they are cards rather than a table.** This dialog
 * used to open on two paragraphs of explanation above a five-column table holding
 * one row, which is a lot of chrome to say "workbench, 2g, bridge" - and the
 * columns were empty for a runtime whose ceilings the service leaves to its own
 * defaults. What an operator came to find out is what an agent gets, so that is
 * what is at the top; the service-wide ceilings are below it, and the sentence
 * about why none of it is editable here is one line rather than a paragraph.
 */
export function PolicyPanel({ connection, onOpenChange }: PolicyPanelProps) {
  const t = useTranslations("sandboxes.policy");
  const { policy, isLoading, error } = useSandboxPolicy(connection?.id ?? null);
  const defaultRuntime = policy?.default_runtime ?? null;

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
          <div className="space-y-6">
            <section className="space-y-2">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {t("runtimesHeading")}
              </h3>

              {policy.runtimes.length === 0 ? (
                <p className="text-destructive text-sm">{t("serviceAllowsNoRuntime")}</p>
              ) : (
                <ul className="space-y-2">
                  {policy.runtimes.map((runtime: SandboxRuntime) => (
                    <li key={runtime.alias} className="rounded-lg border p-3">
                      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <span className="font-mono text-sm font-medium">{runtime.alias}</span>
                        {runtime.alias === defaultRuntime && (
                          <Badge variant="secondary">{t("default")}</Badge>
                        )}
                        {runtime.builds && (
                          <span className="text-muted-foreground text-xs">{t("builtHost")}</span>
                        )}
                      </div>

                      {runtime.description !== "" && (
                        <p className="text-muted-foreground mt-1 text-xs">{runtime.description}</p>
                      )}
                      {runtime.image !== null && (
                        <p className="text-muted-foreground/80 mt-1 font-mono text-xs break-all">
                          {runtime.image}
                        </p>
                      )}

                      {/* Only the ceilings this runtime actually names. An entry
                          that leaves them to the service's defaults said "—"
                          three times, which reads as three limits of nothing
                          rather than as "whatever the service does". */}
                      <dl className="mt-3 grid gap-x-6 gap-y-2 sm:grid-cols-3">
                        {runtime.mem_limit !== null && (
                          <Fact label={t("memory")} value={runtime.mem_limit} />
                        )}
                        {runtime.cpus !== null && (
                          <Fact label={t("cpus")} value={String(runtime.cpus)} />
                        )}
                        {runtime.network_mode !== null && (
                          <Fact label={t("network")} value={runtime.network_mode} />
                        )}
                      </dl>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
                {t("ceilingsHeading")}
              </h3>

              {/* Each one names the variable that sets it. "Idle timeout: 30 min"
                  with no way to change it and nothing saying where it comes from
                  reads as a limit this application chose; it is the service's own
                  boot configuration, and naming the variable is the difference
                  between a dead end and a one-line edit in a compose file. */}
              <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-3">
                <Fact
                  label={t("perOrganization")}
                  value={policy.max_sessions_per_tenant?.toString() ?? "—"}
                  source={t("sandboxdMaxSessionsPer")}
                />
                <Fact
                  label={t("idleTimeout")}
                  value={timeout(policy.idle_timeout)}
                  source={t("sandboxdIdleTimeout")}
                />
                <Fact
                  label={t("keptBetweenTurns")}
                  value={policy.persist_containers === false ? t("notKept") : t("kept")}
                  source={t("sandboxdPersistContainers")}
                />
              </dl>
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
