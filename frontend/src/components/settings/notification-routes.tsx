"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { CHAT_NOTIFICATION_CHANNELS } from "@/lib/notification-preferences-api";
import { getErrorMessage } from "@/lib/api-error";
import { useNotificationRoutes } from "@/hooks/use-notification-routes";
import { ErrorState } from "@/components/states";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SectionCard } from "./settings-section";

export function NotificationRoutes() {
  const t = useTranslations("notificationRoutes");
  const errors = useTranslations("errors");
  const { data, error, isLoading, replace, isSaving } = useNotificationRoutes();
  return (
    <SectionCard title={t("title")} description={t("description")}>
      {error ? (
        <ErrorState description={getErrorMessage(error, errors, t("loadFailed"))} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {CHAT_NOTIFICATION_CHANNELS.map((channel) => {
            const selected = data?.items.find((item) => item.channel === channel);
            const destinations =
              data?.destinations.filter((item) => item.channel === channel) ?? [];
            return (
              <FormField key={channel} label={t(channel)} htmlFor={`notification-route-${channel}`}>
                <Select
                  value={
                    selected ? (selected.available ? selected.session_id : "unavailable") : "off"
                  }
                  disabled={isLoading || isSaving}
                  onValueChange={async (id) => {
                    try {
                      await replace({ channel, session_id: id === "off" ? null : id });
                    } catch (failure) {
                      toast.error(getErrorMessage(failure, errors, t("saveFailed")));
                    }
                  }}
                >
                  <SelectTrigger id={`notification-route-${channel}`}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="off">{t("off")}</SelectItem>
                    {selected && !selected.available && (
                      <SelectItem value="unavailable" disabled>
                        {t("unavailable")}
                      </SelectItem>
                    )}
                    {destinations.map((item) => (
                      <SelectItem key={item.session_id} value={item.session_id}>
                        {t("destination", {
                          bot: item.bot_name,
                          account: item.account_name,
                          id: item.session_id.slice(0, 8),
                        })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {selected && !selected.available && (
                  <p className="text-muted-foreground mt-1 text-xs">{t("unavailable")}</p>
                )}
                {!isLoading && destinations.length === 0 && (
                  <p className="text-muted-foreground mt-1 text-xs">{t("connect")}</p>
                )}
              </FormField>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}
