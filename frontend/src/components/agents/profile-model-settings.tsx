"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";
import { ModelSettingsForm } from "./model-settings-form";
import {
  OptionalSetting,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { ModelSettingsSpec } from "@/types/agents";

const EFFORTS = ["minimal", "low", "medium", "high", "xhigh", "max"] as const;
const SETTINGS = ["temperature", "top_p", "max_tokens", "timeout", "parallel_tool_calls"] as const;

/** Profile defaults use the SDK settings, while the builder edits agent overrides. */
export function ProfileModelSettings({
  value,
  onChange,
  disabled,
}: {
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const t = useTranslations("agents");
  const ui = useTranslations("ui");
  const thinking = useTranslations("capabilityConfig.thinking.effort");
  const settings: ModelSettingsSpec = {};
  for (const field of ["temperature", "top_p", "max_tokens", "timeout"] as const) {
    const setting = value[field];
    if (typeof setting === "number") settings[field] = setting;
  }
  if (typeof value.parallel_tool_calls === "boolean")
    settings.parallel_tool_calls = value.parallel_tool_calls;
  const effort = EFFORTS.find((effort) => effort === value.thinking);
  const selected =
    value.thinking === undefined
      ? "default"
      : value.thinking === true
        ? "on"
        : value.thinking === false
          ? "off"
          : (effort ?? "custom");
  return (
    <div className="space-y-6 border-t pt-4">
      <div className="space-y-1">
        <h4 className="text-sm font-medium">{t("profileDefaults")}</h4>
        <p className="text-muted-foreground text-xs">{t("profileDefaultsHint")}</p>
      </div>
      <OptionalSetting
        htmlFor={`${id}-thinking`}
        label={thinking("title")}
        description={thinking("description")}
        disabled={disabled}
      >
        <Select
          value={selected}
          disabled={disabled}
          onValueChange={(next) => {
            const updated = { ...value };
            if (next === "default") delete updated.thinking;
            else if (next === "on" || next === "off") updated.thinking = next === "on";
            else {
              const effort = EFFORTS.find((effort) => effort === next);
              /* v8 ignore next -- the menu emits only offered efforts; its custom item is disabled */
              if (effort === undefined) return;
              updated.thinking = effort;
            }
            onChange(updated);
          }}
        >
          <SelectTrigger id={`${id}-thinking`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="default">{ui("providerDefault")}</SelectItem>
            <SelectItem value="on">{t("profileThinkingOn")}</SelectItem>
            <SelectItem value="off">{t("profileThinkingOff")}</SelectItem>
            {EFFORTS.map((effort) => (
              <SelectItem key={effort} value={effort}>
                {effort}
              </SelectItem>
            ))}
            {selected === "custom" && (
              <SelectItem value="custom" disabled>
                {t("profileCustomThinking")}
              </SelectItem>
            )}
          </SelectContent>
        </Select>
      </OptionalSetting>
      <ModelSettingsForm
        idPrefix={id}
        value={settings}
        disabled={disabled}
        onChange={(settings) => {
          const updated = { ...value };
          for (const field of SETTINGS) delete updated[field];
          onChange({ ...updated, ...settings });
        }}
      />
    </div>
  );
}
