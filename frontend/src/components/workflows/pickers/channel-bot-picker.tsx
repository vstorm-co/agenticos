"use client";

import Link from "next/link";
import { Bot } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Badge,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useChannelBots, usePermissions } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

export interface ChannelBotPickerProps {
  /** What the control is called: the field's own name, or the picker's when it has none. */
  label?: string;
  /** Offer only this platform's bots - a Slack step's picker lists Slack bots. */
  platform?: string;
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
  const { bots: every, isLoading } = useChannelBots(mayManage);
  const bots = platform === undefined ? every : every.filter((bot) => bot.platform === platform);
  const chosen = bots.find((bot) => bot.id === value);
  const orphaned = mayManage && value !== null && !isLoading && chosen === undefined;

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
                {platform === undefined && <Badge variant="outline">{bot.platform}</Badge>}
                {!bot.is_active && <Badge variant="secondary">{t("pickerBotOff")}</Badge>}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {bots.length === 0 && !isLoading && (
        <p className="text-muted-foreground text-xs">
          {t("pickerBotsEmpty")}{" "}
          <Link href={ROUTES.CHANNELS} className="underline underline-offset-2">
            {t("pickerBotsAdd")}
          </Link>
        </p>
      )}
      {orphaned && <p className="text-foreground/70 text-xs">{t("pickerBotOrphaned")}</p>}
      {error !== undefined && <p className="text-destructive text-xs">{error}</p>}
    </div>
  );
}
