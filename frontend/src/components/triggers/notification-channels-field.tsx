"use client";

import { useTranslations } from "next-intl";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { RoutineNotificationChannel } from "@/types/routines";

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
  const chosen =
    value === null
      ? "inherit"
      : value.length === 0
        ? "none"
        : value.includes("email") && value.includes("push")
          ? "both"
          : value[0];
  return (
    <FormField label={t("label")} htmlFor="routine-notification-channels" description={t("hint")}>
      <Select
        value={chosen}
        onValueChange={(id) => {
          const choice = CHOICES.find((item) => item.id === id);
          if (choice) onChange(choice.channels);
        }}
      >
        <SelectTrigger id="routine-notification-channels">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {CHOICES.map((choice) => (
            <SelectItem key={choice.id} value={choice.id}>
              {t(choice.id)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
