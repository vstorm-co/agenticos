"use client";

import { ChevronDown, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChannelPlatformIcon } from "@/components/channels/channel-platform-icon";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import type { ExposureSurface, ExposureTarget } from "@/types/exposures";

const PLATFORMS: readonly ExposureSurface[] = ["slack", "teams", "telegram", "mattermost"];

export const SURFACE_LABEL: Record<ExposureSurface, string> = {
  slack: "Slack",
  telegram: "Telegram",
  mattermost: "Mattermost",
  // i18n-exempt: a product\'s own name, written the same in every language
  teams: "Microsoft Teams",
};

const TILE =
  "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors";

/**
 * Every chat app the platform answers on, whether or not the organization has
 * a bot there yet.
 *
 * A picker listing only the registered bots was empty for every organization
 * that had not been to Channels first, and an empty picker says nothing about
 * what could go in it. A tile per platform says what is supported; its click
 * binds a free bot, or registers one where there is none.
 */
export function ExposureChannelTiles({
  available,
  separated,
  canRegister,
  disabled,
  onBind,
  onRegister,
}: {
  /** Bots free to bind - a bot answers as one agent, so a bound one is absent. */
  available: ExposureTarget[];
  separated: boolean;
  /** Registering a bot is `channels:manage`, a different permission from binding one. */
  canRegister: boolean;
  disabled: boolean;
  onBind: (botId: string) => void;
  onRegister: (platform: ExposureSurface) => void;
}) {
  const t = useTranslations("agents");

  return (
    <div className={cn("space-y-2", separated && "border-t pt-3")}>
      <p id="exposure-platforms" className="text-sm font-medium">
        {t("addChannel")}
      </p>
      <div role="group" aria-labelledby="exposure-platforms" className="grid gap-2 sm:grid-cols-3">
        {PLATFORMS.map((platform) => {
          const bots = available.filter((bot) => bot.platform === platform);
          const label = SURFACE_LABEL[platform];
          const caption =
            bots.length > 0
              ? t("botsReady", { count: bots.length })
              : canRegister
                ? t("connectABot")
                : t("noBotAskAdmin");
          const body = (
            <>
              <ChannelPlatformIcon platform={platform} />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{label}</span>
                <span className="text-muted-foreground block truncate text-xs">{caption}</span>
              </span>
            </>
          );

          if (bots.length === 0) {
            return (
              <button
                key={platform}
                type="button"
                disabled={disabled || !canRegister}
                onClick={() => onRegister(platform)}
                aria-label={t("registerPlatformBot", { platform: label })}
                className={cn(
                  TILE,
                  "hover:bg-accent disabled:pointer-events-none disabled:opacity-60",
                )}
              >
                {body}
                {canRegister && <Plus className="text-muted-foreground size-4" aria-hidden />}
              </button>
            );
          }

          return (
            <DropdownMenu key={platform}>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={t("addOnPlatform", { platform: label })}
                  className={cn(TILE, "hover:bg-accent disabled:opacity-60")}
                >
                  {body}
                  <ChevronDown className="text-muted-foreground size-4" aria-hidden />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="min-w-56">
                {bots.map((bot) => (
                  <DropdownMenuItem key={bot.id} onSelect={() => onBind(bot.id)}>
                    <span className="min-w-0 flex-1 truncate">{bot.name}</span>
                    {/* Binding to a switched-off bot is legal and answers
                        nothing; this is the one place that says so before
                        somebody wonders why the handle is silent. */}
                    {!bot.is_active && (
                      <span className="text-muted-foreground shrink-0 pl-3 text-xs">
                        {t("inactive")}
                      </span>
                    )}
                  </DropdownMenuItem>
                ))}
                {canRegister && (
                  <>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onSelect={() => onRegister(platform)}>
                      <Plus aria-hidden />
                      {t("registerAnotherBot")}
                    </DropdownMenuItem>
                  </>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          );
        })}
      </div>
    </div>
  );
}
