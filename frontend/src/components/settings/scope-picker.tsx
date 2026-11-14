"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  Label,
  Input,
  MoreOptions,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { ApiKeyScopeCatalog } from "@/types/api-keys";
import { Perm, type Permission } from "@/types/permissions";

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
  disabled = false,
}: {
  catalog: ApiKeyScopeCatalog;
  choice: ScopeChoice;
  id: string;
  disabled?: boolean;
}) {
  const t = useTranslations("apiKeys");
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const shown = catalog.scopes.filter((scope) => scope.toLowerCase().includes(needle));
  const custom = !catalog.presets.some((option) => option.id === choice.preset);
  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={id}>{t("access")}</Label>
        <Select value={choice.preset} onValueChange={choice.setPreset} disabled={disabled}>
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
      </div>
      {custom ? (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor={`${id}-search`}>{t("permissionSearch")}</Label>
            <span className="text-muted-foreground shrink-0 text-xs">
              {t("scopeCount", { count: choice.scopes.length })}
            </span>
          </div>
          <Input
            type="search"
            onKeyDown={(event) => {
              if (event.key === "Enter") event.preventDefault();
            }}
            id={`${id}-search`}
            value={query}
            disabled={disabled}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("permissionPlaceholder")}
          />
          <fieldset disabled={disabled} className="grid min-w-0 gap-2 sm:grid-cols-2">
            <legend className="sr-only">{t("access")}</legend>
            {shown.map((scope) => (
              <label
                key={scope}
                className="hover:bg-accent/50 has-[[data-state=checked]]:bg-accent flex min-h-11 min-w-0 cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 font-mono text-xs"
              >
                <Checkbox
                  disabled={disabled}
                  checked={choice.custom.includes(scope)}
                  onCheckedChange={(on) => choice.toggle(scope, on === true)}
                />
                <span className="[overflow-wrap:anywhere]">{scope}</span>
              </label>
            ))}
          </fieldset>
          {shown.length === 0 && (
            <p className="text-muted-foreground py-3 text-center text-sm">{t("noPermissions")}</p>
          )}
          {catalog.scopes.includes(Perm.personalConsent) && (
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t("personalConsentWhy")}
            </p>
          )}
        </div>
      ) : (
        <MoreOptions label={t("permissionDetails", { count: choice.scopes.length })}>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("accessWhy")}</p>
          <ul className="flex flex-wrap gap-1.5">
            {choice.scopes.map((scope) => (
              <li
                key={scope}
                className="bg-muted max-w-full rounded-md px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]"
              >
                {scope}
              </li>
            ))}
          </ul>
          {catalog.scopes.includes(Perm.personalConsent) && (
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t("personalConsentWhy")}
            </p>
          )}
        </MoreOptions>
      )}
    </>
  );
}
