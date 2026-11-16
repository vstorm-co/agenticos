"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Input, Label, Switch, Textarea } from "@/components/ui";
import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import { ModelSettingsForm } from "@/components/agents/model-settings-form";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import type { AgentSpec } from "@/types/agents";

export function ChatAgentSettingsFields({
  spec,
  disabled,
  update,
}: {
  spec: AgentSpec;
  disabled: boolean;
  update: (patch: Partial<AgentSpec>) => void;
}) {
  const t = useTranslations("chat.agentSettings");
  const id = useId();
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Label htmlFor={`${id}-name`}>{t("name")}</Label>
        <Input
          id={`${id}-name`}
          maxLength={128}
          value={spec.name}
          disabled={disabled}
          aria-invalid={!spec.name.trim()}
          onChange={(event) => update({ name: event.target.value })}
        />
        {!spec.name.trim() && <p className="text-destructive text-xs">{t("nameRequired")}</p>}
      </div>
      <div className="space-y-2">
        <Label htmlFor={`${id}-description`}>{t("description")}</Label>
        <Textarea
          id={`${id}-description`}
          maxLength={1000}
          rows={2}
          value={spec.description ?? ""}
          disabled={disabled}
          onChange={(event) => update({ description: event.target.value || null })}
        />
        <p className="text-muted-foreground text-xs">{t("descriptionHint")}</p>
      </div>
      <details open className="group border-t pt-4">
        <summary className="cursor-pointer text-sm font-medium">{t("instructions")}</summary>
        <div className="mt-3 space-y-2">
          <Label htmlFor={`${id}-instructions`} className="sr-only">
            {t("instructions")}
          </Label>
          <Textarea
            id={`${id}-instructions`}
            rows={10}
            value={spec.instructions}
            className="min-h-48 resize-y font-mono text-xs"
            disabled={disabled}
            onChange={(event) => update({ instructions: event.target.value })}
          />
          <p className="text-muted-foreground text-xs">{t("instructionsHint")}</p>
        </div>
      </details>
      <ChatAgentModelSettings spec={spec} disabled={disabled} update={update} />
      <ChatAgentCapabilities spec={spec} disabled={disabled} update={update} />
    </div>
  );
}

function ChatAgentModelSettings({
  spec,
  disabled,
  update,
}: Parameters<typeof ChatAgentSettingsFields>[0]) {
  const t = useTranslations("chat.agentSettings");
  const { profiles, profilesStatus } = useModelProviders();
  return (
    <details className="border-t pt-4">
      <summary className="cursor-pointer text-sm font-medium">{t("model")}</summary>
      <div className="mt-3 space-y-3">
        <p className="text-muted-foreground text-xs">{t("modelHint")}</p>
        <ModelProfilePicker
          profiles={profiles}
          profilesStatus={profilesStatus}
          value={spec.model_profile_id ?? null}
          onChange={(model_profile_id) => update({ model_profile_id })}
          disabled={disabled || profilesStatus !== "loaded"}
        />
        <ModelSettingsForm
          value={spec.model_settings}
          disabled={disabled}
          onChange={(model_settings) => update({ model_settings })}
        />
      </div>
    </details>
  );
}

function ChatAgentCapabilities({
  spec,
  disabled,
  update,
}: Parameters<typeof ChatAgentSettingsFields>[0]) {
  const t = useTranslations("chat.agentSettings");
  const guide = useCapabilityGuide();
  return (
    <details className="border-t pt-4">
      <summary className="cursor-pointer text-sm font-medium">{t("capabilities")}</summary>
      <div className="mt-3 space-y-3">
        <p className="text-muted-foreground text-xs">{t("capabilitiesHint")}</p>
        {spec.capabilities.length === 0 && (
          <p className="text-muted-foreground text-xs">{t("noCapabilities")}</p>
        )}
        {spec.capabilities.map((binding) => {
          const name = guide(binding.id)?.name ?? binding.id;
          return (
            <label
              key={binding.id}
              className="flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm"
            >
              <span>{name}</span>
              <Switch
                aria-label={name}
                checked={binding.enabled !== false}
                disabled={disabled}
                onCheckedChange={(enabled) =>
                  update({
                    capabilities: spec.capabilities.map((item) =>
                      item.id === binding.id ? { ...item, enabled } : item,
                    ),
                  })
                }
              />
            </label>
          );
        })}
      </div>
    </details>
  );
}
