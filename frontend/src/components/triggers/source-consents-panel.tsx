"use client";

import Link from "next/link";
import { useId, useState } from "react";
import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";
import { useRoutineSources } from "@/hooks/use-routine-sources";
import { Button, Spinner, ChoiceGroup } from "@/components/ui";
import { ErrorState } from "@/components/states/error-state";
import { getErrorMessage } from "@/lib/api-error";
import type { Trigger } from "@/types/triggers";
import type { RoutineSourceItem, RoutineSourceMode } from "@/lib/routine-sources-api";
import { useBranding } from "@/components/branding/branding-provider";

export function SourceConsentsPanel({
  trigger,
  showApprove = true,
  mode: controlledMode,
  onModeChange,
  disabled = false,
}: {
  trigger: Trigger;
  showApprove?: boolean;
  mode?: RoutineSourceMode;
  onModeChange?: (mode: RoutineSourceMode) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("triggers.sourceConsents");
  const errors = useTranslations("errors");
  const { data, isLoading, error, replace, refetch } = useRoutineSources(
    trigger.agent_id,
    trigger.id,
  );
  const modeId = useId();
  const [chosen, setChosen] = useState<{ token: string; mode: RoutineSourceMode } | null>(null);
  const storedMode = data?.mode ?? "restricted";
  const mode =
    controlledMode ??
    (chosen?.token === data?.review_token ? chosen?.mode : undefined) ??
    storedMode;
  const changed = mode !== storedMode;
  const pending = disabled || replace.isPending;
  return (
    <section aria-label={t("title")} className="space-y-3 rounded-lg border p-3">
      <h3 className="text-sm font-medium">{t("title")}</h3>
      <p className="text-muted-foreground text-sm">{t("description")}</p>
      {isLoading ? (
        <Spinner />
      ) : error ? (
        <div className="space-y-2">
          <ErrorState
            title={getErrorMessage(error, errors)}
            cta={{ label: t("retry"), onClick: () => void refetch() }}
          />
          <Link
            className="text-sm underline underline-offset-4"
            href={`${ROUTES.AGENT_DETAIL(trigger.agent_id)}?highlight=agent-mcp`}
          >
            {t("inspectAgent")}
          </Link>
        </div>
      ) : (
        data && (
          <>
            <div className="space-y-2">
              <p id={modeId} className="text-sm font-medium">
                {t("modeLabel")}
              </p>
              <ChoiceGroup
                labelledBy={modeId}
                value={mode}
                options={[
                  { value: "follow_agent", label: t("followAgent") },
                  { value: "restricted", label: t("restricted") },
                ]}
                disabled={pending || (!showApprove && !onModeChange)}
                onChange={(next) => {
                  setChosen({ token: data.review_token, mode: next });
                  onModeChange?.(next);
                }}
              />
              <p className="text-muted-foreground text-sm">
                {t(mode === "follow_agent" ? "followHint" : "restrictedHint")}
              </p>
            </div>
            <p className="text-sm">
              {t(
                changed
                  ? "selectionPending"
                  : mode === "follow_agent"
                    ? "followCurrent"
                    : data.current
                      ? "current"
                      : "changed",
              )}
            </p>
            {data.items ? (
              <SourceGroups items={data.items} />
            ) : (
              <ul className="max-h-44 space-y-1 overflow-y-auto text-xs break-all">
                {[...data.resources, ...data.accounts].map((name) => (
                  <li key={name}>{name}</li>
                ))}
              </ul>
            )}
            {data.unavailable_sources.length > 0 && (
              <div className="space-y-2">
                <p role="status" className="text-sm">
                  {t(mode === "follow_agent" ? "followUnavailable" : "unavailable", {
                    names: data.unavailable_sources.join(", "),
                  })}
                </p>
                <Link
                  className="text-sm underline underline-offset-4"
                  href={`${ROUTES.AGENT_DETAIL(trigger.agent_id)}?highlight=agent-mcp`}
                >
                  {t("inspectAgent")}
                </Link>
              </div>
            )}
            {showApprove && (
              <Button
                variant="outline"
                disabled={
                  pending ||
                  (mode === "restricted" && data.unavailable_sources.length > 0) ||
                  (data.current && !changed)
                }
                onClick={() => replace.mutate({ review_token: data.review_token, mode })}
              >
                {t(mode === "follow_agent" ? "saveMode" : "accept")}
              </Button>
            )}
          </>
        )
      )}
    </section>
  );
}

/**
 * The reviewed sources grouped by kind, each kind folded to a count, and each
 * source by its name - its id only on hover, for whoever has to look it up.
 */
function SourceGroups({ items }: { items: RoutineSourceItem[] }) {
  const t = useTranslations("triggers.sourceConsents");
  const { appName } = useBranding();
  const kinds = new Map<RoutineSourceItem["kind"], RoutineSourceItem[]>();
  for (const item of items) kinds.set(item.kind, [...(kinds.get(item.kind) ?? []), item]);
  return (
    <div className="max-h-60 space-y-1 overflow-y-auto">
      {[...kinds.entries()].map(([kind, sources]) => (
        <details key={kind} className="rounded-md border px-2 py-1">
          <summary className="cursor-pointer text-sm">
            {t("kindCount", { name: t("kind", { kind }), count: sources.length })}
          </summary>
          <ul className="space-y-1 py-1 pl-4 text-xs break-words">
            {sources.map((source) => (
              <li key={`${source.id}:${source.detail}`} title={source.id ?? undefined}>
                {kind === "platform" ? appName : (source.name ?? t("unnamed"))}
                {source.detail && <span className="text-muted-foreground"> · {source.detail}</span>}
              </li>
            ))}
          </ul>
        </details>
      ))}
    </div>
  );
}
