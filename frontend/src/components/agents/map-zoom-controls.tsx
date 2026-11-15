"use client";

import { Maximize, ZoomIn, ZoomOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";

/** Zoom in, zoom out and reset, in the top right corner of a pannable diagram. */
export function MapZoomControls({
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
}) {
  const t = useTranslations("agents");
  return (
    <div className="absolute top-2 right-2 z-10 flex gap-1">
      <Button type="button" variant="outline" size="icon" aria-label={t("zoom")} onClick={onZoomIn}>
        <ZoomIn className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={t("zoomOut")}
        onClick={onZoomOut}
      >
        <ZoomOut className="h-4 w-4" />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon"
        aria-label={t("resetView")}
        onClick={onReset}
      >
        <Maximize className="h-4 w-4" />
      </Button>
    </div>
  );
}
