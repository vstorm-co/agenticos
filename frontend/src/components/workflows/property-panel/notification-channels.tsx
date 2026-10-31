"use client";

import { Bell, Mail } from "lucide-react";
import { useTranslations } from "next-intl";
import { Checkbox, Label } from "@/components/ui";
import { cn } from "@/lib/utils";

export function NotificationChannels({
  value,
  disabled,
  onChange,
}: {
  value: unknown;
  disabled?: boolean;
  onChange: (value: string[]) => void;
}) {
  const t = useTranslations("workflows");
  const picked = Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : ["in_app"];
  return (
    <fieldset className="space-y-2">
      <legend className="mb-2 text-sm font-medium">{t("notificationChannels")}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {(["in_app", "email"] as const).map((channel) => {
          const Icon = channel === "email" ? Mail : Bell;
          const on = picked.includes(channel);
          return (
            <Label
              key={channel}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-xl border p-3",
                on && "bg-accent border-foreground/25",
              )}
            >
              <Checkbox
                checked={on}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  onChange(
                    checked ? [...picked, channel] : picked.filter((item) => item !== channel),
                  )
                }
              />
              <Icon className="text-muted-foreground size-4" aria-hidden />
              <span>{t(channel === "email" ? "notificationEmail" : "notificationInApp")}</span>
            </Label>
          );
        })}
      </div>
      <p className="text-muted-foreground text-xs">{t("notificationChannelHint")}</p>
    </fieldset>
  );
}
