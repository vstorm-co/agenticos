"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  FormField,
  Input,
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

interface SubscriptionFieldsProps {
  provider: EventSource;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  disabled?: boolean;
}

const filters = {
  linear: ["event_types", "actions"],
  hubspot: ["subscription_types", "property_names"],
  zendesk: ["event_types"],
} as const;

export function SubscriptionFields(props: SubscriptionFieldsProps) {
  const t = useTranslations("eventSources");
  const { provider, config, onChange, disabled } = props;
  if (provider === "linear" || provider === "hubspot" || provider === "zendesk") {
    return (
      <div className="space-y-3">
        {filters[provider].map((key) => (
          <ListFilter
            key={key}
            id={`source-filter-${key}`}
            label={t(`filters.${key}`)}
            value={config[key]}
            disabled={disabled}
            onChange={(values) => {
              const next = { ...config };
              if (values.length) next[key] = values;
              else delete next[key];
              onChange(next);
            }}
          />
        ))}
        <p className="text-muted-foreground text-xs">{t("filters.help")}</p>
      </div>
    );
  }
  return <PresetFields {...props} />;
}

function ListFilter({
  id,
  label,
  value,
  disabled,
  onChange,
}: {
  id: string;
  label: string;
  value: unknown;
  disabled?: boolean;
  onChange: (values: string[]) => void;
}) {
  // Keep the typed separator visible while the author enters the next value.
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <FormField label={label} htmlFor={id}>
      <Input
        id={id}
        value={draft ?? (Array.isArray(value) ? value.join(", ") : "")}
        disabled={disabled}
        onChange={(event) => {
          const text = event.target.value;
          setDraft(text);
          onChange(
            text
              .split(",")
              .map((part) => part.trim())
              .filter(Boolean),
          );
        }}
        onBlur={() => setDraft(null)}
      />
    </FormField>
  );
}

/** Reuse the provider catalog's event filters without registering a provider hook. */
function PresetFields({ provider, config, onChange, disabled }: SubscriptionFieldsProps) {
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
