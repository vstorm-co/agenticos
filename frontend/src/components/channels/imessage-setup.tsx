"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useRegisterChannelWebhook } from "@/hooks/use-channel-bots";

export function ImessageSetup({ botId, unsaved }: { botId: string; unsaved: boolean }) {
  const t = useTranslations("pages.channels");
  const registration = useRegisterChannelWebhook();
  return (
    <div className="border-border space-y-3 rounded-lg border p-3">
      <p className="text-muted-foreground text-sm">{t("imessageWebhookHint")}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={registration.isPending || unsaved}
        onClick={() => registration.mutate(botId)}
      >
        {t("imessageRegisterWebhook")}
      </Button>
    </div>
  );
}
