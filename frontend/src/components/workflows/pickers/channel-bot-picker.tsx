"use client";

import dynamic from "next/dynamic";
import { useState } from "react";
import type { ChannelPlatform } from "@/types/channels";
import { Bot, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Button,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useChannelBots, usePermissions } from "@/hooks";
import { Perm } from "@/types/permissions";

const AddChannelDialog = dynamic(() =>
  import("@/components/channels/add-channel-dialog").then((module) => module.AddChannelDialog),
);

function channelPlatform(value: string | undefined): ChannelPlatform | undefined {
  return value === "slack" || value === "telegram" || value === "mattermost" || value === "teams"
    ? value
    : undefined;
}

export interface ChannelBotPickerProps {
  /** What the control is called: the field's own name, or the picker's when it has none. */
  label?: string;
  /** Offer only these platforms' bots - a Slack step's picker lists Slack bots. */
  platform?: string | readonly string[];
  /** The chosen bot's id, or null while none is. */
  value: string | null;
  onChange: (botId: string | null) => void;
  disabled?: boolean;
  error?: string;
}

/**
 * Which of the organization's channel bots a channel step acts as.
 *
 * Acting as a bot needs `channels:manage` - it speaks for the whole
 * organization - and so does listing them, so a member without it is told why
 * instead of shown an empty list. A switched-off bot is offered, marked, because
 * the step would refuse it at the next run and a silent absence would hide that.
 */
export function ChannelBotPicker({
  value,
  onChange,
  disabled,
  error,
  label,
  platform,
}: ChannelBotPickerProps) {
  const t = useTranslations("workflows");
  const caption = label ?? t("pickerBotLabel");
  const { can } = usePermissions();
  const mayManage = can(Perm.channelsManage);
  const { bots: every, isLoading, create } = useChannelBots(mayManage);
  const [adding, setAdding] = useState(false);
  const platforms = typeof platform === "string" ? [platform] : platform;
  const bots =
    platforms === undefined ? every : every.filter((bot) => platforms.includes(bot.platform));
  const chosen = bots.find((bot) => bot.id === value);
  const lost = mayManage && value !== null && !isLoading && chosen === undefined;
  const misplaced = lost && every.some((bot) => bot.id === value);
  const orphaned = lost && !misplaced;
  // A step with one platform names it; one open to several lists them.
  const only = platforms?.length === 1 ? platforms[0] : undefined;

  if (!mayManage) {
    return <p className="text-muted-foreground text-xs">{t("pickerBotNeedsPermission")}</p>;
  }

  return (
    <div className="space-y-2">
      <Label>{caption}</Label>
      <Select value={value ?? ""} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger aria-label={caption}>
          <SelectValue placeholder={t("pickerBotPlaceholder")} />
        </SelectTrigger>
        <SelectContent>
          {bots.map((bot) => (
            <SelectItem key={bot.id} value={bot.id}>
              <span className="flex items-center gap-2">
                <Bot className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{bot.name}</span>
                {(platforms === undefined || platforms.length > 1) && (
                  <Badge variant="outline">{bot.platform}</Badge>
                )}
                {!bot.is_active && <Badge variant="secondary">{t("pickerBotOff")}</Badge>}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {bots.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-xs">{t("pickerBotsEmpty")}</p>
      )}
      {!disabled && (
        <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
          <Plus className="size-3.5" aria-hidden />
          {t("pickerBotConnect")}
        </Button>
      )}
      {adding && (
        <AddChannelDialog
          open
          onOpenChange={setAdding}
          initialPlatform={channelPlatform(only)}
          isPending={create.isPending}
          onSubmit={async (data) => {
            const bot = await create.mutateAsync(data);
            onChange(bot.id);
            setAdding(false);
          }}
        />
      )}
      {orphaned && <p className="text-foreground/70 text-xs">{t("pickerBotOrphaned")}</p>}
      {misplaced && (
        <p className="text-foreground/70 text-xs">
          {only === undefined
            ? t("pickerBotWrongPlatform")
            : t("pickerBotWrongPlatformOne", {
                platform: `${only.charAt(0).toUpperCase()}${only.slice(1)}`,
              })}
        </p>
      )}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
