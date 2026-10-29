"use client";

import { FormField, Switch } from "@/components/ui";
import type { ChannelPlatform } from "@/types/channels";
import { useTranslations } from "next-intl";

/** Which delivered group messages may start a run; direct chats always answer. */
export function MentionPolicyFields({
  idPrefix,
  platform,
  enabled,
  onChange,
}: {
  idPrefix: string;
  platform: ChannelPlatform;
  enabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const t = useTranslations("pages.channels");
  return (
    <div className="space-y-2">
      <FormField
        label={t("respondToBroadcasts")}
        htmlFor={`${idPrefix}-broadcasts`}
        description={t("respondToBroadcastsHint")}
      >
        <Switch id={`${idPrefix}-broadcasts`} checked={enabled} onCheckedChange={onChange} />
      </FormField>
      {platform === "teams" && (
        <p className="text-muted-foreground text-xs">{t("broadcastsTeamsHint")}</p>
      )}
      {platform === "telegram" && (
        <p className="text-muted-foreground text-xs">{t("broadcastsTelegramHint")}</p>
      )}
    </div>
  );
}
