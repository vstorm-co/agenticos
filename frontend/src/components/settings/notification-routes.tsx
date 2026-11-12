"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { CHAT_NOTIFICATION_CHANNELS } from "@/lib/notification-preferences-api";
import { getErrorMessage } from "@/lib/api-error";
import { useNotificationRoutes } from "@/hooks/use-notification-routes";
import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import { ErrorState, LoadingState } from "@/components/states";
import {
  FormField,
  MoreOptions,
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
  const tc = useTranslations("common");
  const { data, error, isLoading, replace, isSaving, refetch } = useNotificationRoutes();
  const connected = CHAT_NOTIFICATION_CHANNELS.filter(
    (channel) =>
      data?.destinations.some((item) => item.channel === channel) ||
      data?.items.some((item) => item.channel === channel),
  );
  const remaining = CHAT_NOTIFICATION_CHANNELS.filter((channel) => !connected.includes(channel));
  const renderChannels = (channels: typeof connected) => (
    <div className="grid gap-4 sm:grid-cols-2">
      {channels.map((channel) => {
        const selected = data?.items.find((item) => item.channel === channel);
        const destinations = data?.destinations.filter((item) => item.channel === channel) ?? [];
        return (
          <FormField
            key={channel}
            label={
              <span className="flex items-center gap-2">
                <ChannelPlatformIcon platform={channel} className="size-6" />
                {t(channel)}
              </span>
            }
            htmlFor={`notification-route-${channel}`}
          >
            <Select
              value={selected ? (selected.available ? selected.session_id : "unavailable") : "off"}
              disabled={isLoading || isSaving || (destinations.length === 0 && !selected)}
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
          </FormField>
        );
      })}
    </div>
  );
  return (
    <SectionCard title={t("title")} description={t("description")}>
      {error ? (
        <ErrorState
          description={getErrorMessage(error, errors, t("loadFailed"))}
          cta={{ label: tc("retry"), onClick: () => void refetch() }}
        />
      ) : isLoading ? (
        <LoadingState variant="pending" />
      ) : (
        <div className="space-y-4">
          {connected.length > 0 ? (
            renderChannels(connected)
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-2" aria-hidden>
                {CHAT_NOTIFICATION_CHANNELS.map((channel) => (
                  <ChannelPlatformIcon key={channel} platform={channel} />
                ))}
              </div>
              <p className="text-muted-foreground text-sm leading-relaxed">{t("connect")}</p>
            </div>
          )}
          {remaining.length > 0 && (
            <MoreOptions label={t("platformOptions")}>
              <p className="text-muted-foreground text-xs leading-relaxed">{t("connect")}</p>
              {renderChannels(remaining)}
            </MoreOptions>
          )}
        </div>
      )}
    </SectionCard>
  );
}
