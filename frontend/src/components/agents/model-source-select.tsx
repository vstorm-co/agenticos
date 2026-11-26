"use client";

import { useTranslations } from "next-intl";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  SUBSCRIPTION_PROVIDERS,
  SUBSCRIPTION_MARK,
  subscriptionChoice,
} from "@/lib/subscription-accounts-api";

const CUSTOM = new Set([
  "cliproxyapi",
  "litellm",
  "openai_compatible",
  "anthropic_compatible",
  "ollama",
]);

/** Friendly source names are UI choices; saved provider IDs remain unchanged. */
export function modelSourceOptions(
  providers: readonly { id: string; label: string }[],
  subscriptions: boolean,
  t: (key: string) => string,
): {
  id: string;
  label: string;
  mark: string;
  group: "subscriptions" | "organization" | "custom";
}[] {
  return [
    ...(subscriptions
      ? SUBSCRIPTION_PROVIDERS.map((provider) => ({
          id: subscriptionChoice(provider),
          label: t(`subscriptionAccounts.providers.${provider}`),
          mark: SUBSCRIPTION_MARK[provider],
          group: "subscriptions" as const,
        }))
      : []),
    ...[...providers]
      .sort((a, b) => a.label.localeCompare(b.label))
      .filter((provider) => provider.id !== "subscription_accounts")
      .map((provider) => ({
        ...provider,
        label: provider.id === "cliproxyapi" ? t("modelSources.gateway") : provider.label,
        mark: provider.id,
        group: CUSTOM.has(provider.id) ? ("custom" as const) : ("organization" as const),
      })),
  ];
}

export function ModelSourceSelect({
  id,
  value,
  onChange,
  providers,
  subscriptions,
  disabled,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  providers: readonly { id: string; label: string }[];
  subscriptions: boolean;
  disabled?: boolean;
}) {
  const t = useTranslations();
  const options = modelSourceOptions(providers, subscriptions, t);
  return (
    <div className="space-y-1.5">
      <Select
        value={value === "subscription_accounts" ? "" : value}
        onValueChange={onChange}
        disabled={disabled}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={t("agents.chooseProvider")} />
        </SelectTrigger>
        <SelectContent className="max-h-80">
          {(["subscriptions", "organization", "custom"] as const).map((group) => (
            <SelectGroup key={group}>
              {options.some((entry) => entry.group === group) && (
                <SelectLabel>{t(`modelSources.${group}`)}</SelectLabel>
              )}
              {options
                .filter((entry) => entry.group === group)
                .map((entry) => (
                  <SelectItem key={entry.id} value={entry.id} textValue={entry.label}>
                    <ProviderRow provider={entry.mark} name={entry.label} />
                  </SelectItem>
                ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
