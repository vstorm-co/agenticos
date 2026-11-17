"use client";

import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { EventOptions } from "@/components/triggers/event-options";
import { usePortalCatalog } from "@/hooks/use-portals";
import type { EventSource } from "@/types/triggers";

/** Reuse the provider catalog's event filters without registering a provider hook. */
export function SubscriptionFields({
  provider,
  config,
  onChange,
  disabled,
}: {
  provider: EventSource;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("eventSources");
  const { portals, error } = usePortalCatalog();
  const presets = portals.find((portal) => portal.event_source === provider)?.presets ?? [];
  const selected = presets.find((preset) =>
    Object.entries(preset.event_config ?? {}).every(
      ([key, value]) => JSON.stringify(config[key]) === JSON.stringify(value),
    ),
  );
  return (
    <div className="space-y-3">
      <Label htmlFor="source-event-preset">{t("eventPreset")}</Label>
      <Select
        value={selected?.key ?? "current"}
        disabled={disabled}
        onValueChange={(key) => {
          const preset = presets.find((preset) => preset.key === key);
          if (preset) onChange({ ...preset.event_config });
        }}
      >
        <SelectTrigger id="source-event-preset">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="current" disabled>
            {t("currentFilters")}
          </SelectItem>
          {presets.map((preset) => (
            <SelectItem key={preset.key} value={preset.key}>
              {preset.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {t("presetError")}
        </p>
      )}
      {selected && <p className="text-muted-foreground text-xs">{selected.description}</p>}
      <EventOptions source={provider} config={config} onChange={onChange} />
    </div>
  );
}
