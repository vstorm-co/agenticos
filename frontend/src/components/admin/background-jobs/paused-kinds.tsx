"use client";

import { PauseCircle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Alert, AlertDescription, AlertTitle, Button } from "@/components/ui";
import { formatDateTime } from "@/lib/utils";
import type { BackgroundKind } from "@/types/background-jobs";

/**
 * The kinds the circuit breaker stopped, with what it said, and the one way back.
 *
 * Nothing restarts a paused kind on its own - the decision for #2219 - so this is
 * where the deployment's owner finds out what is piling up and resumes it once
 * the cause is fixed. A pause is a kind in one organization, or the whole kind,
 * and each says which. Absent when nothing is paused.
 */
export function PausedKinds({
  kinds,
  onResume,
  resuming,
}: {
  kinds: BackgroundKind[];
  onResume: (kind: BackgroundKind) => void;
  /** The breaker being resumed, if one is. */
  resuming: Pick<BackgroundKind, "kind" | "organization_id"> | null;
}) {
  const t = useTranslations("pages.backgroundJobs");
  const locale = useLocale();
  const paused = kinds.filter((kind) => kind.paused_at !== null);
  if (paused.length === 0) return null;
  return (
    <Alert variant="destructive">
      <PauseCircle className="h-4 w-4" />
      <AlertTitle>{t("pausedTitle", { count: paused.length })}</AlertTitle>
      <AlertDescription>
        <ul className="mt-2 space-y-3">
          {paused.map((kind) => (
            <li
              key={`${kind.kind}:${kind.organization_id ?? ""}`}
              className="flex flex-wrap items-start justify-between gap-3"
            >
              <div className="min-w-0">
                <p className="font-mono text-xs font-medium">{kind.kind}</p>
                {/* Paused for one organization, the rest still run (#2248). */}
                <p className="text-xs font-medium">
                  {kind.organization_name === null
                    ? t("pausedEverywhere")
                    : t("pausedFor", { organization: kind.organization_name })}
                </p>
                <p className="text-xs">
                  {t("pausedSince", { time: formatDateTime(kind.paused_at!, locale) })}
                </p>
                {kind.paused_reason && <p className="mt-0.5 text-xs">{kind.paused_reason}</p>}
              </div>
              <Button
                size="sm"
                variant="outline"
                disabled={
                  resuming?.kind === kind.kind && resuming.organization_id === kind.organization_id
                }
                onClick={() => onResume(kind)}
              >
                {t("resume")}
              </Button>
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
