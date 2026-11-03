"use client";

import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import {
  FormField,
  Checkbox,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { RoutineNotificationChannel } from "@/types/routines";
import { CHAT_NOTIFICATION_CHANNELS } from "@/lib/notification-preferences-api";

const CHANNELS: RoutineNotificationChannel[] = ["email", "push", ...CHAT_NOTIFICATION_CHANNELS];

const CHOICES: { id: string; channels: RoutineNotificationChannel[] | null }[] = [
  { id: "inherit", channels: null },
  { id: "none", channels: [] },
  { id: "email", channels: ["email"] },
  { id: "push", channels: ["push"] },
  { id: "both", channels: ["email", "push"] },
];

export function NotificationChannelsField({
  value,
  onChange,
}: {
  value: RoutineNotificationChannel[] | null;
  onChange: (channels: RoutineNotificationChannel[] | null) => void;
}) {
  const t = useTranslations("routineNotifications");
  const channelNames = useTranslations("notificationRoutes");
  const id = useId();
  const [custom, setCustom] = useState(
    value?.some((channel) => channel !== "email" && channel !== "push") ?? false,
  );
  const useCustom =
    custom || (value?.some((channel) => channel !== "email" && channel !== "push") ?? false);
  const chosen = useCustom
    ? "custom"
    : value === null
      ? "inherit"
      : value.length === 0
        ? "none"
        : value.includes("email") && value.includes("push")
          ? "both"
          : value[0];
  return (
    <FormField label={t("label")} htmlFor={id} description={t("hint")}>
      <Select
        value={chosen}
        onValueChange={(id) => {
          if (id === "custom") {
            setCustom(true);
            onChange(value ?? []);
            return;
          }
          setCustom(false);
          const choice = CHOICES.find((item) => item.id === id);
          if (choice) onChange(choice.channels);
        }}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CHOICES.map((choice) => (
            <SelectItem key={choice.id} value={choice.id}>
              {t(choice.id)}
            </SelectItem>
          ))}
          <SelectItem value="custom">{t("custom")}</SelectItem>
        </SelectContent>
      </Select>
      {useCustom && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-3">
          {CHANNELS.map((channel) => (
            <label key={channel} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={value?.includes(channel) ?? false}
                onCheckedChange={(checked) => {
                  const selected = new Set(value ?? []);
                  if (checked === true) selected.add(channel);
                  else selected.delete(channel);
                  onChange(CHANNELS.filter((item) => selected.has(item)));
                }}
              />
              {channelNames(channel)}
            </label>
          ))}
        </div>
      )}
    </FormField>
  );
}
