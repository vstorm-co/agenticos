"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { TableIcon, WorkflowIcon } from "@/components/icons/product-icons";
import type { ResourceIconName } from "@/types/resource-icons";
import { STARTER_ICON_IDS, STARTER_ICONS } from "@/lib/starter-icons";
import { cn } from "@/lib/utils";
import { Button } from "./button";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

export const RESOURCE_ICONS = { table: TableIcon, workflow: WorkflowIcon, ...STARTER_ICONS };
const ICON_NAMES = ["table", "workflow", ...STARTER_ICON_IDS] as const;
type Kind = "table" | "workflow";

/** The same quiet mark in a resource's catalog, header and dashboard. */
export function ResourceIcon({
  kind,
  icon,
  className,
}: {
  kind: Kind;
  icon?: ResourceIconName | null;
  className?: string;
}) {
  const Mark = RESOURCE_ICONS[icon ?? kind];
  return (
    <span
      aria-hidden="true"
      data-resource-icon={icon ?? kind}
      className={cn(
        "bg-muted text-muted-foreground border-foreground/5 inline-flex size-10 shrink-0 items-center justify-center rounded-xl border",
        className,
      )}
    >
      <Mark className="size-5" aria-hidden="true" />
    </span>
  );
}

export function ResourceIconPicker({
  kind,
  icon,
  onChange,
  disabled = false,
}: {
  kind: Kind;
  icon?: ResourceIconName | null;
  onChange: (icon: ResourceIconName | null) => Promise<unknown>;
  disabled?: boolean;
}) {
  const t = useTranslations("resourceAppearance");
  const labels = useTranslations("starterIcons");
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const choose = async (next: ResourceIconName | null) => {
    if (saving || disabled) return;
    setSaving(true);
    try {
      await onChange(next);
      setOpen(false);
    } catch {
      // The resource mutation reports the refusal. Keep its picker available to retry.
    } finally {
      setSaving(false);
    }
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!saving) setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="size-11 shrink-0 rounded-xl p-0"
          aria-label={t("change")}
          disabled={disabled || saving}
        >
          <ResourceIcon kind={kind} icon={icon} />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-64 p-3" aria-label={t("change")}>
        <p className="mb-3 text-sm font-medium">{t("title")}</p>
        <div className="grid grid-cols-4 gap-1">
          {ICON_NAMES.map((id) => {
            const Mark = RESOURCE_ICONS[id];
            const label = id === "table" || id === "workflow" ? t(id) : labels(id);
            return (
              <Button
                key={id}
                type="button"
                variant={(icon ?? kind) === id ? "secondary" : "ghost"}
                size="icon"
                className="size-11"
                disabled={disabled || saving}
                aria-label={label}
                title={label}
                aria-pressed={(icon ?? kind) === id}
                onClick={() => void choose(id)}
              >
                <Mark className="size-5" aria-hidden />
              </Button>
            );
          })}
        </div>
        <Button
          type="button"
          variant="ghost"
          className="mt-3 w-full"
          disabled={disabled || saving || icon == null}
          onClick={() => void choose(null)}
        >
          {t("reset")}
        </Button>
      </PopoverContent>
    </Popover>
  );
}
