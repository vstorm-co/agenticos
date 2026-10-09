"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { ApiKeyScopeCatalog } from "@/types/api-keys";
import type { Permission } from "@/types/permissions";

const CUSTOM = "custom";

export interface ScopeChoice {
  preset: string;
  setPreset: (preset: string) => void;
  custom: Permission[];
  toggle: (scope: Permission, on: boolean) => void;
  /** What would be granted: the preset's permissions, or the ticked ones under Custom. */
  scopes: Permission[];
  reset: () => void;
}

/** The state behind a {@link ScopePicker}: a preset, or a hand-picked set. */
export function useScopeChoice(catalog: ApiKeyScopeCatalog): ScopeChoice {
  const first = catalog.presets[0]?.id ?? CUSTOM;
  const [preset, setPreset] = useState<string>(first);
  const [custom, setCustom] = useState<Permission[]>([]);
  // "Custom" matches no preset, so the ticked permissions are what is granted.
  const chosen = catalog.presets.find((choice) => choice.id === preset);
  return {
    preset,
    setPreset,
    custom,
    toggle: (scope, on) =>
      setCustom((current) => (on ? [...current, scope] : current.filter((s) => s !== scope))),
    scopes: chosen ? chosen.scopes : custom,
    reset: () => {
      setPreset(first);
      setCustom([]);
    },
  };
}

/**
 * What a key or a connected application may do: a preset for the usual jobs, or
 * the catalog under "Custom". The catalog holds only what the caller has - a
 * credential never reaches further than the person who handed it out.
 */
export function ScopePicker({
  catalog,
  choice,
  id,
}: {
  catalog: ApiKeyScopeCatalog;
  choice: ScopeChoice;
  id: string;
}) {
  const t = useTranslations("apiKeys");
  const custom = !catalog.presets.some((option) => option.id === choice.preset);
  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={id}>{t("access")}</Label>
        <Select value={choice.preset} onValueChange={choice.setPreset}>
          <SelectTrigger id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {catalog.presets.map((option) => (
              <SelectItem key={option.id} value={option.id}>
                {t(`preset.${option.id}`)}
              </SelectItem>
            ))}
            <SelectItem value={CUSTOM}>{t("preset.custom")}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("accessWhy")}</p>
      </div>
      {custom ? (
        <fieldset className="grid gap-2 sm:grid-cols-2" aria-label={t("access")}>
          {catalog.scopes.map((scope) => (
            <label key={scope} className="flex items-center gap-2 font-mono text-xs">
              <Checkbox
                checked={choice.custom.includes(scope)}
                onCheckedChange={(on) => choice.toggle(scope, on === true)}
              />
              {scope}
            </label>
          ))}
        </fieldset>
      ) : (
        <p className="text-muted-foreground font-mono text-xs">{choice.scopes.join(", ")}</p>
      )}
    </>
  );
}
