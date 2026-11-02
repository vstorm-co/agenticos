"use client";

import { Settings2, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";

import { Badge, Switch } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { CapabilityCatalogEntry } from "@/types/agents";

import { DRAWN_ART, DRAWN_HUE } from "./art.drawn";
import { CAPABILITY_ART, CAPABILITY_HUE } from "./art.generated";
import "./capability-art.css";

/** A hue for a capability the canvas drew nothing for, steady across renders. */
function hueOf(id: string): number {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % 360;
}

/**
 * What a capability does, drawn: the canvas's isometric scene for it, or - for
 * a capability the canvas has no scene for - its initial on the same stage.
 */
export function CapabilityArt({
  id,
  name,
  off = false,
}: {
  id: string;
  name: string;
  off?: boolean;
}) {
  const svg = CAPABILITY_ART[id] ?? DRAWN_ART[id];
  const style = { "--h": CAPABILITY_HUE[id] ?? DRAWN_HUE[id] ?? hueOf(id) } as CSSProperties;
  const stage = "stage v-B h-20 sm:h-24";
  return (
    <div className={cn("cap-art", off && "is-off")} style={style}>
      {svg !== undefined ? (
        // Static markup generated from our own design canvas - no input of
        // anybody's reaches it. Inline rather than an <img>, so the scene takes
        // the console's theme and its CSS animation.
        <div className={stage} dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className={cn(stage, "grid place-items-center")}>
          <span className="text-foreground/40 text-4xl font-semibold" aria-hidden>
            {name.charAt(0)}
          </span>
        </div>
      )}
    </div>
  );
}

/** Marks a capability the starter agent has, which a new agent starts with. */
export function RecommendedBadge({ className }: { className?: string }) {
  const t = useTranslations("agents");
  return (
    <Badge variant="success" className={cn("px-1.5 py-0 text-[11px] leading-4", className)}>
      {t("capabilityRecommended")}
    </Badge>
  );
}

/** One capability as a card: its scene, its name and switch, what it does, how many tools. */
export function CapabilityCard({
  entry,
  enabled,
  focused,
  disabled,
  onFocus,
  onToggle,
}: {
  entry: CapabilityCatalogEntry;
  enabled: boolean;
  focused: boolean;
  disabled?: boolean;
  onFocus: () => void;
  onToggle: () => void;
}) {
  const t = useTranslations("agents");
  return (
    <div
      data-tour={`capability-${entry.id}`}
      className={cn(
        "group bg-card flex w-full flex-col overflow-hidden rounded-xl border transition-colors",
        focused ? "border-foreground/40" : "hover:border-foreground/25",
      )}
    >
      <button
        type="button"
        onClick={onFocus}
        aria-current={focused ? "true" : undefined}
        aria-label={t("capabilitySettingsTitle", { name: entry.name })}
        className="focus-visible:ring-ring flex flex-1 flex-col text-left outline-none focus-visible:ring-2 focus-visible:ring-inset"
      >
        <div className="relative w-full overflow-hidden border-b">
          <CapabilityArt id={entry.id} name={entry.name} off={!enabled} />
          {entry.recommended && (
            <RecommendedBadge className="bg-background/90 absolute top-2 left-2 shadow-sm backdrop-blur" />
          )}
        </div>
        <div className="w-full space-y-1 px-3 pt-2.5 pb-1">
          <span className="flex items-center gap-1.5">
            <span
              className={cn(
                "min-w-0 flex-1 text-sm font-medium",
                !enabled && "text-muted-foreground",
              )}
            >
              {entry.name}
            </span>
            {entry.side_effecting && (
              <ShieldAlert
                className="text-muted-foreground size-3 shrink-0"
                aria-label={t("actsWorld")}
              />
            )}
            <Settings2 className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
          </span>
          <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
            {entry.description}
          </span>
        </div>
      </button>
      <div className="text-muted-foreground mt-auto flex items-center justify-between gap-2 px-3 pt-1 pb-2.5 text-[11px]">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className={cn("size-1.5 rounded-full", enabled ? "bg-success" : "bg-foreground/25")}
          />
          {t("capabilityToolCount", { count: entry.tools.length })}
        </span>
        <Switch
          checked={enabled}
          disabled={disabled}
          aria-label={t("giveThisAgent", { name: entry.name })}
          onCheckedChange={onToggle}
          className="shrink-0"
        />
      </div>
    </div>
  );
}
