"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { getErrorMessage } from "@/lib/api-error";
import { connectionModelLabel } from "@/lib/model-profiles";
import { useAuthStore } from "@/stores";
import type { ClaudeSubscriptionModel } from "@/types/personal-subscriptions";

const MODELS: readonly ClaudeSubscriptionModel[] = ["sonnet", "opus", "haiku"];

/** Save normal model profiles, so the existing agent and chat pickers use this connection. */
export function ClaudeSubscriptionModels({
  connected,
  disabled,
}: {
  connected: boolean;
  disabled: boolean;
}) {
  const t = useTranslations("claudeSubscription");
  const tErrors = useTranslations("errors");
  const id = useId();
  const user = useAuthStore((state) => state.user);
  const { createProfile, profiles, profilesStatus, refetchProfiles } = useModelProviders();
  const [model, setModel] = useState<ClaudeSubscriptionModel>("sonnet");
  const [error, setError] = useState<string | null>(null);
  const own = profiles.filter(
    (profile) => profile.provider === "claude-subscription" && profile.usage_scope === "personal",
  );
  const saved = own.some((profile) => profile.model === model);
  const busy = disabled || createProfile.isPending;

  if (!connected && profilesStatus !== "failed" && own.length === 0) return null;

  return (
    <div className="border-border space-y-3 border-t pt-4">
      {connected && user && (
        <>
          <p className="text-muted-foreground text-xs">{t("modelHint")}</p>
          <Select
            value={model}
            onValueChange={(value) => {
              if (MODELS.includes(value as ClaudeSubscriptionModel))
                setModel(value as ClaudeSubscriptionModel);
              setError(null);
            }}
            disabled={busy}
          >
            <FormField htmlFor={`${id}-model`} label={t("model")}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
            </FormField>
            <SelectContent>
              {MODELS.map((choice) => (
                <SelectItem key={choice} value={choice}>
                  {t(`models.${choice}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            loading={createProfile.isPending}
            disabled={busy || saved || profilesStatus !== "loaded"}
            onClick={() => {
              setError(null);
              createProfile.mutate(
                {
                  provider: "claude-subscription",
                  model,
                  secret_id: null,
                  label: connectionModelLabel(
                    t(`models.${model}`),
                    t("connectionLabel", { person: user.email }),
                    profiles.map((profile) => profile.label),
                  ),
                },
                {
                  onError: (failure) => setError(getErrorMessage(failure, tErrors)),
                },
              );
            }}
          >
            {saved ? t("modelAlreadySaved") : t("addModel")}
          </Button>
        </>
      )}
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      {profilesStatus === "failed" ? (
        <p role="alert" className="text-destructive text-xs">
          {t("modelsUnavailable")}
          <Button type="button" variant="ghost" size="sm" onClick={() => void refetchProfiles()}>
            {t("retry")}
          </Button>
        </p>
      ) : own.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-sm font-medium">{t("savedModels")}</h4>
          <ul className="text-muted-foreground space-y-1 text-xs">
            {own.map((profile) => (
              <li key={profile.id}>{profile.label}</li>
            ))}
          </ul>
          <p className="text-muted-foreground text-xs">
            {t(connected ? "chooseSavedModel" : "reconnectModels")}
          </p>
        </div>
      ) : null}
    </div>
  );
}
