"use client";

import { RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";

import { Alert, AlertDescription, Button } from "@/components/ui";
import type { ChangeEvent } from "@/types/change-events";

interface RemoteChangeBannerProps {
  change: ChangeEvent;
  onReload: () => void;
  onKeepMine: () => void;
}

/**
 * Says that what is being edited here was changed somewhere else, by whom and
 * through what, and lets the editor choose. Nothing is replaced until they do:
 * the edits on this page are theirs, and the other change is somebody's too.
 */
export function RemoteChangeBanner({ change, onReload, onKeepMine }: RemoteChangeBannerProps) {
  const t = useTranslations("liveUpdates");
  return (
    <Alert variant="warning">
      <RefreshCw className="h-4 w-4" />
      <AlertDescription className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1">
          {t("changedElsewhere", {
            actor: change.actor_name,
            surface: t(`surface.${change.surface}`),
          })}
        </span>
        <span className="flex gap-2">
          <Button size="sm" variant="outline" onClick={onKeepMine}>
            {t("keepMine")}
          </Button>
          <Button size="sm" onClick={onReload}>
            {t("reload")}
          </Button>
        </span>
      </AlertDescription>
    </Alert>
  );
}
