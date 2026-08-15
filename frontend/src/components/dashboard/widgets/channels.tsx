"use client";

import { useTranslations } from "next-intl";

import { useChannelBots } from "@/hooks";
import { SurfaceIcon } from "@/components/runs/surface-icon";
import { StatusList } from "../primitives/status-list";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/**
 * Where the agents can be reached, and whether the door is open.
 *
 * `surfaces` counts runs *per* surface, which is a different question: it says
 * where the work came from, and a channel nobody used this period is simply
 * absent from it. This card lists what is registered, so a bot that was
 * switched off - or registered and never bound to an agent - is visible as
 * itself rather than as a gap in somebody else's bar chart.
 *
 * Gated on `channels:manage`, which is what `GET /channels/bots` demands; the
 * hook is told so rather than firing a predictable 403 and drawing it as a
 * failure.
 */
export function ChannelsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.channels");
  const { bots, isLoading, error, refetch } = useChannelBots(true);

  if (isLoading) {
    return (
      <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
        <WidgetSkeleton />
      </WidgetFrame>
    );
  }

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : bots.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <StatusList
          rows={bots.map((bot) => ({
            label: bot.name,
            sub: t(`platforms.${bot.platform}`),
            // The platform's own brand mark, from the module the run table and
            // the surface filter draw from - a channel wears one face across
            // the product or the reader learns two (#144's rule).
            icon: <SurfaceIcon surface={bot.platform} className="size-4" />,
            // A webhook bot answers when the platform calls it; a polling bot
            // has to be running. Which mode it is in is the difference between
            // "silent because nobody asked" and "silent because nothing is
            // listening", so the row says which.
            pill: bot.is_active
              ? bot.webhook_mode
                ? t("webhook")
                : t("polling")
              : t("switchedOff"),
            tone: bot.is_active ? "ok" : "neutral",
          }))}
        />
      )}
    </WidgetFrame>
  );
}
