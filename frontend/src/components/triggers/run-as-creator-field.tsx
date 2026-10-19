"use client";

import { useTranslations } from "next-intl";

import { Checkbox, Label } from "@/components/ui";
import type { TriggerType } from "@/types/triggers";

/**
 * Whether a trigger acts as the person who made it (#2027).
 *
 * On, a fire reaches that person's memory and their own MCP connections, as their
 * own chat does - the morning "read my inbox" the default cannot do. Only that
 * person may turn it on, so for anybody else the box can only be cleared: the
 * server refuses the rest, and an edit by somebody else to what the trigger does
 * clears it anyway. What it opens is said per kind, because an event's prompt
 * carries content from outside and so reads memory without writing it.
 */
export function RunAsCreatorField({
  checked,
  onChange,
  type,
  isCreator,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  type: TriggerType;
  /** Whether the person looking is the one the trigger would act as. */
  isCreator: boolean;
}) {
  const t = useTranslations("triggers");
  return (
    <Label className="flex items-start gap-2 font-normal sm:col-span-2">
      <Checkbox
        checked={checked}
        disabled={!isCreator && !checked}
        onCheckedChange={(next) => onChange(next === true)}
      />
      <span>
        <span className="text-sm">{isCreator ? t("runAsMe") : t("runAsCreator")}</span>
        <span className="text-muted-foreground block text-xs">
          {!isCreator
            ? t("runAsCreatorOthersHint")
            : type === "event"
              ? t("runAsMeEventHint")
              : t("runAsMeScheduleHint")}
        </span>
      </span>
    </Label>
  );
}
