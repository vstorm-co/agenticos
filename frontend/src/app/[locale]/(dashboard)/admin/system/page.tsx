"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Cpu, Database, HardDrive, RefreshCw, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { LoadingState } from "@/components/states";
import { Button } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { cn, getErrorMessage } from "@/lib/utils";
import type { CheckStatus, SystemHealth } from "@/types/admin";
import { useTranslations } from "next-intl";

const REFRESH_INTERVAL_MS = 30_000;

/** Each service's words live in the catalog; `words` names the key. */
const META: Record<string, { words: string; icon: LucideIcon }> = {
  database: { words: "serviceDatabase", icon: Database },
  redis: { words: "serviceRedis", icon: Zap },
  vector_store: { words: "serviceVectorStore", icon: HardDrive },
  model_access: { words: "serviceModelAccess", icon: Cpu },
};

const STATUS_DOT: Record<CheckStatus, string> = {
  healthy: "bg-chart",
  unhealthy: "bg-destructive",
  unconfigured: "bg-muted-foreground",
  not_checked: "bg-muted-foreground",
};

/** The catalog key for each state, not the word: the word is in `messages/en.json`. */
const STATUS_WORDS: Record<CheckStatus, string> = {
  healthy: "stateHealthy",
  unhealthy: "stateUnhealthy",
  unconfigured: "stateUnconfigured",
  not_checked: "stateNotChecked",
};

const STATUS_TEXT: Record<CheckStatus, string> = {
  healthy: "text-foreground",
  unhealthy: "text-destructive",
  unconfigured: "text-muted-foreground",
  not_checked: "text-muted-foreground",
};

export default function SystemHealthPage() {
  const t = useTranslations("pages.admin");
  const [auto, setAuto] = useState(true);

  // Through the query layer, where server data belongs. `refetchInterval` is
  // the auto-refresh the second effect hand-rolled with `setInterval`, and it
  // stops while the tab is hidden - which the interval did not, so a backgrounded
  // dashboard was polling the health endpoint every thirty seconds all day.
  const {
    data: health = null,
    isPending: loading,
    error,
    refetch,
  } = useQuery({
    queryKey: qk.admin.system(),
    queryFn: () => apiClient.get<SystemHealth>("/admin/system"),
    refetchInterval: auto ? REFRESH_INTERVAL_MS : false,
  });

  const load = () => void refetch();

  const checks = health?.checks ?? [];

  const summary = useMemo(() => {
    if (!checks.length) return null;
    const failing = checks.filter((check) => check.status === "unhealthy");
    if (failing.length) {
      const names = failing.map((check) =>
        META[check.key] ? t(META[check.key]!.words) : check.key,
      );
      return { tone: "bad" as const, label: t("failingServices", { names: names.join(", ") }) };
    }
    const unconfigured = checks.filter((check) => check.status !== "healthy");
    if (unconfigured.length) {
      return {
        tone: "mixed" as const,
        label: t("someUnconfigured", { count: unconfigured.length }),
      };
    }
    return { tone: "good" as const, label: t("everyCheckPassed") };
  }, [checks]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button
          size="sm"
          variant="outline"
          onClick={() => setAuto((a) => !a)}
          className={cn(auto && "bg-muted")}
        >
          <span
            aria-hidden
            className={cn("h-1.5 w-1.5 rounded-full", auto ? "bg-chart" : "bg-muted-foreground")}
          />
          Auto-refresh {auto ? "on" : "off"}
        </Button>
        <Button size="sm" variant="outline" onClick={load}>
          <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} />
          {t("refresh2")}
        </Button>
      </div>

      {summary && (
        <section className="border-border bg-card rounded-xl border p-5">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <span className="bg-muted text-foreground inline-flex h-10 w-10 items-center justify-center rounded-lg">
                {summary.tone === "bad" ? (
                  <AlertCircle className="h-5 w-5" />
                ) : (
                  <CheckCircle2 className="h-5 w-5" />
                )}
              </span>
              <div>
                <p className="text-muted-foreground text-xs">{t("overallStatus")}</p>
                <div className="mt-1 flex items-center gap-2">
                  <span
                    aria-hidden
                    className={cn(
                      "h-2 w-2 rounded-full",
                      summary.tone === "bad" ? "bg-destructive" : "bg-chart",
                    )}
                  />
                  <p className="text-foreground text-base font-semibold">{summary.label}</p>
                </div>
              </div>
            </div>
            {health && (
              <span className="text-muted-foreground text-xs">
                Checked {new Date(health.checked_at).toLocaleTimeString()}
              </span>
            )}
          </div>
        </section>
      )}

      {loading && !health ? (
        <LoadingState variant="stats" rows={4} />
      ) : error ? (
        <div className="border-border bg-card rounded-xl border p-8 text-center">
          <AlertCircle className="text-destructive mx-auto h-6 w-6" />
          <p className="text-foreground mt-3 text-sm font-medium">{t("couldnAposTFetch")}</p>
          <p className="text-muted-foreground mt-1 text-xs">
            {getErrorMessage(error, t("failedFetchHealth"))}
          </p>
        </div>
      ) : (
        <section className="border-border bg-card rounded-xl border">
          <div className="border-border border-b px-5 py-4">
            <h2 className="text-foreground text-sm font-semibold">{t("services")}</h2>
            <p className="text-muted-foreground text-xs">{t("eachRowSaysWhat")}</p>
          </div>
          <ul className="divide-border divide-y">
            {checks.map((check) => {
              const meta = META[check.key];
              const Icon = meta?.icon ?? Database;
              return (
                <li key={check.key} className="flex items-start gap-3 px-5 py-4">
                  <span className="bg-muted text-muted-foreground mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground text-sm font-medium">
                      {meta ? t(meta.words) : check.key}
                      {meta && (
                        <span className="text-muted-foreground font-normal">
                          {" · "}
                          {t(`${meta.words}Detail`)}
                        </span>
                      )}
                    </p>
                    <p className="text-muted-foreground mt-0.5 text-xs">{check.detail}</p>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1 pl-1">
                    <div className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className={cn("h-2 w-2 rounded-full", STATUS_DOT[check.status])}
                      />
                      <span
                        className={cn(
                          "text-xs font-medium whitespace-nowrap",
                          STATUS_TEXT[check.status],
                        )}
                      >
                        {t(STATUS_WORDS[check.status])}
                      </span>
                    </div>
                    {check.latency_ms !== null && (
                      <span className="text-muted-foreground text-[11px] tabular-nums">
                        {check.latency_ms} ms
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <p className="text-muted-foreground text-xs">{t("everyStatusHereComes")}</p>
    </div>
  );
}
