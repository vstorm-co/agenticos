"use client";

import { Settings2, ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState, type CSSProperties } from "react";

import { Switch } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { CapabilityCatalogEntry } from "@/types/agents";

import { CAPABILITY_ART, CAPABILITY_HUE, type CapabilityArtStyle } from "./art.generated";
import "./capability-art.css";

/** The Toolbox's views while the illustrated cards are on trial: today's list, or one style. */
export type CapabilityView = "list" | CapabilityArtStyle;

const VIEWS: readonly CapabilityView[] = ["list", "isometric", "crew"];
const VIEW_KEY = "capability-view";

/** Each style's stage class in the stylesheet the canvas generated. */
const STAGE: Record<CapabilityArtStyle, string> = {
  isometric: "v-B",
  crew: "v-F",
};

/**
 * Which view the reader last chose, kept in this browser only.
 *
 * A trial switch, not a setting: it decides nothing for anybody else, and goes
 * once one style is picked.
 */
export function useCapabilityView(): [CapabilityView, (view: CapabilityView) => void] {
  // Read once, on the first render: the Toolbox renders after the agent loads,
  // in the browser, so there is no server render for this to disagree with.
  const [view, setView] = useState<CapabilityView>(() => {
    try {
      const stored = window.localStorage.getItem(VIEW_KEY);
      return stored !== null && (VIEWS as readonly string[]).includes(stored)
        ? (stored as CapabilityView)
        : "list";
    } catch {
      // Storage refused (a private window): the list it opens on is the default.
      return "list";
    }
  });
  const choose = (next: CapabilityView) => {
    setView(next);
    try {
      window.localStorage.setItem(VIEW_KEY, next);
    } catch {
      // Remembered for this visit only.
    }
  };
  return [view, choose];
}

/** A small segmented control to try each card style on the real Toolbox. */
export function CapabilityViewSwitch({
  value,
  onChange,
  className,
}: {
  value: CapabilityView;
  onChange: (view: CapabilityView) => void;
  className?: string;
}) {
  const t = useTranslations("agents");
  return (
    <div
      role="radiogroup"
      aria-label={t("capabilityView")}
      className={cn("bg-foreground/[0.05] inline-flex w-fit gap-0.5 rounded-lg p-0.5", className)}
    >
      {VIEWS.map((view) => (
        <button
          key={view}
          type="button"
          role="radio"
          aria-checked={value === view}
          onClick={() => onChange(view)}
          className={cn(
            "rounded-md px-2 py-0.5 text-[11px] font-medium transition-colors",
            value === view
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(`capabilityView_${view}`)}
        </button>
      ))}
    </div>
  );
}

/** A hue for a capability the canvas drew nothing for, steady across renders. */
function hueOf(id: string): number {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return hash % 360;
}

/**
 * What a capability does, drawn: the canvas's scene for it in one style, or -
 * for a capability the canvas has no scene for - its initial on the same stage.
 */
export function CapabilityArt({
  id,
  name,
  artStyle,
  off = false,
}: {
  id: string;
  name: string;
  artStyle: CapabilityArtStyle;
  off?: boolean;
}) {
  const svg = CAPABILITY_ART[artStyle][id];
  const style = { "--h": CAPABILITY_HUE[id] ?? hueOf(id) } as CSSProperties;
  const stage = cn("stage aspect-video", STAGE[artStyle]);
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

/** One capability as a card: its scene, its name and switch, what it does, how many tools. */
export function CapabilityCard({
  entry,
  artStyle,
  enabled,
  focused,
  disabled,
  onFocus,
  onToggle,
}: {
  entry: CapabilityCatalogEntry;
  artStyle: CapabilityArtStyle;
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
        "group bg-card flex w-full flex-col overflow-hidden border transition-colors",
        artStyle === "crew" ? "rounded-2xl" : "rounded-xl",
        focused ? "border-foreground/40" : "hover:border-foreground/25",
      )}
    >
      <button
        type="button"
        onClick={onFocus}
        aria-current={focused ? "true" : undefined}
        aria-label={entry.name}
        className={cn(
          "block overflow-hidden text-left",
          artStyle === "crew" && "m-2 mb-0 rounded-xl",
          artStyle === "isometric" && "border-b",
        )}
      >
        <CapabilityArt id={entry.id} name={entry.name} artStyle={artStyle} off={!enabled} />
      </button>
      <div className="flex flex-1 flex-col gap-1 px-3 py-2.5">
        <div className="flex items-start gap-2">
          <button type="button" onClick={onFocus} className="min-w-0 flex-1 text-left">
            <span className="flex items-center gap-1.5">
              <span className={cn("text-sm font-medium", !enabled && "text-muted-foreground")}>
                {entry.name}
              </span>
              {entry.side_effecting && (
                <ShieldAlert
                  className="text-muted-foreground h-3 w-3"
                  aria-label={t("actsWorld")}
                />
              )}
            </span>
          </button>
          <Switch
            checked={enabled}
            disabled={disabled}
            aria-label={t("giveThisAgent", { name: entry.name })}
            onCheckedChange={onToggle}
            className="shrink-0"
          />
        </div>
        <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
          {entry.description}
        </p>
        <div className="text-muted-foreground mt-auto flex items-center gap-1.5 pt-1 text-[11px]">
          <span
            aria-hidden
            className={cn("size-1.5 rounded-full", enabled ? "bg-success" : "bg-foreground/25")}
          />
          {t("capabilityToolCount", { count: entry.tools.length })}
          <button
            type="button"
            onClick={onFocus}
            aria-label={t("capabilitySettingsTitle", { name: entry.name })}
            className="hover:text-foreground ml-auto flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium transition-colors"
          >
            <Settings2 className="size-3" aria-hidden />
            {t("capabilityOpenSettings")}
          </button>
        </div>
      </div>
    </div>
  );
}
