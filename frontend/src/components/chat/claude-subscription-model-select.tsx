"use client";

import { useId } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { usableForAgents } from "@/lib/model-profiles";
import type { ModelProfile } from "@/types/providers";

/** An explicit profile choice: native subscriptions have no API key for the other picker to select. */
export function ClaudeSubscriptionModelSelect({
  profiles,
  value,
  disabled,
  onChange,
}: {
  profiles: readonly ModelProfile[];
  value: string | null;
  disabled: boolean;
  onChange: (profileId: string) => void;
}) {
  const t = useTranslations("claudeSubscription");
  const id = useId();
  const native = profiles.filter(
    (profile) => profile.provider === "claude-subscription" && profile.usage_scope === "personal",
  );
  const selected = native.find((profile) => profile.id === value);

  return (
    <div className="space-y-2" data-tour="chat-subscription-model">
      {native.length > 0 && (
        <>
          <Label htmlFor={id}>{t("savedModels")}</Label>
          <Select
            value={selected?.id ?? ""}
            disabled={disabled}
            onValueChange={(next) => {
              if (native.some((profile) => profile.id === next && usableForAgents(profile)))
                onChange(next);
            }}
          >
            <SelectTrigger id={id}>
              <SelectValue placeholder={t("chooseSaved")} />
            </SelectTrigger>
            <SelectContent>
              {native.map((profile) => (
                <SelectItem
                  key={profile.id}
                  value={profile.id}
                  disabled={!usableForAgents(profile)}
                >
                  {profile.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selected && !usableForAgents(selected) && (
            <p className="text-muted-foreground text-xs">{t("reconnectModels")}</p>
          )}
        </>
      )}
      <Link
        href={ROUTES.SETTINGS_AI_CONNECTIONS}
        className="text-muted-foreground text-xs underline underline-offset-4"
      >
        {t(native.length > 0 ? "manageConnection" : "connect")}
      </Link>
    </div>
  );
}
