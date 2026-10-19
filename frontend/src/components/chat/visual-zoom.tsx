"use client";

import { ZoomIn, ZoomOut } from "lucide-react";
import { useTranslations } from "next-intl";

import { IconButton } from "@/components/ui";
import { cn } from "@/lib/utils";

/** The zoom levels a visual steps through; 1 is the drawing fitted to its box. */
export const ZOOM_STEPS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4] as const;

/** Zoom out, the level (which resets it) and zoom in, for one visual. */
export function VisualZoom({
  zoom,
  onZoom,
  className,
}: {
  zoom: number;
  onZoom: (zoom: number) => void;
  className?: string;
}) {
  const t = useTranslations("chat.visuals");
  const at = ZOOM_STEPS.findIndex((step) => step === zoom);
  return (
    <div className={cn("flex shrink-0 items-center", className)}>
      <IconButton
        aria-label={t("zoomOut")}
        title={t("zoomOut")}
        disabled={at <= 0}
        onClick={() => onZoom(ZOOM_STEPS[at - 1]!)}
      >
        <ZoomOut className="size-4" />
      </IconButton>
      <button
        type="button"
        title={t("zoomReset")}
        aria-label={t("zoomReset")}
        onClick={() => onZoom(1)}
        className="text-muted-foreground hover:text-foreground w-11 shrink-0 text-center text-xs tabular-nums"
      >
        {t("zoomLevel", { zoom })}
      </button>
      <IconButton
        aria-label={t("zoomIn")}
        title={t("zoomIn")}
        disabled={at >= ZOOM_STEPS.length - 1}
        onClick={() => onZoom(ZOOM_STEPS[at + 1]!)}
      >
        <ZoomIn className="size-4" />
      </IconButton>
    </div>
  );
}
