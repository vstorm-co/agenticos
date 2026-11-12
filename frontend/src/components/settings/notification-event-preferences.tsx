"use client";

import { useRef, useState } from "react";
import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  useListControls,
} from "@/components/ui";
import { useNotificationPreferences } from "@/hooks";
import { glideOrJump } from "@/lib/motion";
import { getErrorMessage } from "@/lib/api-error";
import {
  CHAT_NOTIFICATION_CHANNELS,
  type ChatNotificationChannel,
  type NotificationChannel,
} from "@/lib/notification-preferences-api";
import { CHANNEL_LABEL, PREFERENCE_EVENTS } from "./notification-event-catalog";
import { SectionCard } from "./settings-section";

const events = [...PREFERENCE_EVENTS];

export function NotificationEventPreferences() {
  const t = useTranslations("pages.settings");
  const tc = useTranslations("common");
  const errors = useTranslations("errors");
  const rows = useRef<HTMLUListElement>(null);
  const [chatChannel, setChatChannel] = useState<ChatNotificationChannel>("slack");
  const [pending, setPending] = useState<Set<string>>(new Set());
  const { isEnabled, setPreference, isLoading, error, retry } = useNotificationPreferences();
  const list = useListControls({
    items: events,
    pageSize: 6,
    matches: (event, query) =>
      `${t(event.words)} ${t(`${event.words}Trigger`)}`.toLowerCase().includes(query),
  });
  const toggle = async (eventType: string, channel: NotificationChannel, enabled: boolean) => {
    const key = `${eventType}:${channel}`;
    if (isLoading || pending.has(key)) return;
    setPending((current) => new Set(current).add(key));
    try {
      await setPreference(eventType, channel, enabled);
    } catch (failure) {
      toast.error(getErrorMessage(failure, errors, t("failedSavePreference")));
    } finally {
      setPending((current) => {
        const next = new Set(current);
        next.delete(key);
        return next;
      });
    }
  };
  return (
    <SectionCard
      title={t("notificationPreferences")}
      description={t("notificationPreferencesDescription")}
    >
      {error ? (
        <ErrorState description={error} cta={{ label: tc("retry"), onClick: retry }} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row">
            <SearchInput
              value={list.query}
              onChange={list.setQuery}
              placeholder={t("notificationSearch")}
              className="w-full sm:w-full"
            />
            <Select
              value={chatChannel}
              onValueChange={(value) => {
                const channel = CHAT_NOTIFICATION_CHANNELS.find((item) => item === value);
                if (channel) setChatChannel(channel);
              }}
            >
              <SelectTrigger
                aria-label={t("chatChannelPreferences")}
                className="w-full sm:w-56 sm:shrink-0"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CHAT_NOTIFICATION_CHANNELS.map((channel) => (
                  <SelectItem key={channel} value={channel}>
                    <span className="flex items-center gap-2">
                      <ChannelPlatformIcon platform={channel} className="size-5 bg-transparent" />
                      {t(CHANNEL_LABEL[channel])}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {isLoading ? (
            <LoadingState variant="pending" />
          ) : list.visible.length === 0 ? (
            <EmptyState
              icon={Search}
              title={t("notificationNoMatches")}
              description={t("notificationSearchHint")}
              cta={{ label: t("notificationClearSearch"), onClick: () => list.setQuery("") }}
              className="border-0"
            />
          ) : (
            <ul ref={rows} className="scroll-mt-32 space-y-3 lg:scroll-mt-6">
              {list.visible.map((event) => (
                <li
                  key={event.eventType}
                  aria-label={t(event.words)}
                  className="flex min-w-0 flex-col gap-4 rounded-xl border p-3 sm:p-4 lg:flex-row lg:items-center"
                >
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <span className="bg-muted text-muted-foreground grid size-9 shrink-0 place-items-center rounded-lg">
                      <event.icon className="size-4" aria-hidden />
                    </span>
                    <div className="min-w-0 space-y-1">
                      <h3 className="text-sm font-medium [overflow-wrap:anywhere]">
                        {t(event.words)}
                      </h3>
                      <p className="text-muted-foreground text-xs leading-relaxed">
                        {t(`${event.words}Trigger`)}
                      </p>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:w-80 lg:shrink-0">
                    {[...event.channels, chatChannel].map((channel) => (
                      <label
                        key={channel}
                        className="bg-muted/40 flex min-w-0 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg px-2 py-1.5"
                      >
                        <span className="text-muted-foreground text-center text-xs [overflow-wrap:anywhere]">
                          {t(CHANNEL_LABEL[channel])}
                        </span>
                        <Switch
                          aria-label={`${t(event.words)} - ${t(CHANNEL_LABEL[channel])}`}
                          checked={isEnabled(event.eventType, channel)}
                          disabled={isLoading || pending.has(`${event.eventType}:${channel}`)}
                          onCheckedChange={(enabled) =>
                            void toggle(event.eventType, channel, enabled)
                          }
                        />
                      </label>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
          <Pager
            page={list.page}
            pageCount={list.pageCount}
            matched={list.matched}
            total={list.total}
            onPage={(page) => {
              list.setPage(page);
              rows.current?.scrollIntoView({ block: "start", behavior: glideOrJump() });
            }}
            counted={t("notificationEventCount", { count: list.total })}
          />
        </div>
      )}
    </SectionCard>
  );
}
