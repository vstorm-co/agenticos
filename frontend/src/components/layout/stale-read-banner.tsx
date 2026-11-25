"use client";

import { useCallback, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { getErrorMessage } from "@/lib/api-error";
import { stoppedPolling } from "@/lib/live-polling";

/**
 * The strip that says part of the open page stopped updating.
 *
 * A live session, check or run keeps its last answer on screen when a read of it
 * fails, and its polling stops there (`livePolling`). Without this the page would
 * look current while nothing on it moves any more. Retry reads every stopped
 * query again; one that answers resumes its own polling and the strip goes.
 */
export function StaleReadBanner() {
  const t = useTranslations("layout");
  const common = useTranslations("common");
  const tErrors = useTranslations("errors");
  const queryClient = useQueryClient();
  const cache = queryClient.getQueryCache();
  const subscribe = useCallback((notify: () => void) => cache.subscribe(notify), [cache]);
  const snapshot = useCallback(
    () =>
      cache
        .findAll({ predicate: stoppedPolling })
        .map((query) => query.queryHash)
        .join("\n"),
    [cache],
  );
  useSyncExternalStore(subscribe, snapshot, snapshot);
  const first = cache.findAll({ predicate: stoppedPolling })[0];
  if (first === undefined) return null;
  return (
    <div
      role="alert"
      className="bg-destructive/10 text-foreground flex flex-wrap items-center gap-x-3 gap-y-1 border-b px-4 py-2 text-sm"
    >
      <AlertCircle className="text-destructive h-4 w-4 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1">
        {t("staleRead", { reason: getErrorMessage(first.state.error, tErrors) })}
      </p>
      <Button
        size="sm"
        variant="outline"
        type="button"
        onClick={() => void queryClient.refetchQueries({ predicate: stoppedPolling })}
      >
        {common("retry")}
      </Button>
    </div>
  );
}
