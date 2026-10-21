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
import type { TriggerOverlap } from "@/types/triggers";

const POLICIES: TriggerOverlap[] = ["skip", "queue", "allow"];

/**
 * What a schedule does when it comes due while its previous run is still going (#2219).
 *
 * The caption says what the chosen policy costs, because each one trades
 * something: skipping loses the occurrence, queueing runs the agent back to
 * back, allowing pays for two runs at once into one run log.
 */
export function OverlapField({
  value,
  onChange,
}: {
  value: TriggerOverlap;
  onChange: (value: TriggerOverlap) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <FormField
      label={t("overlapLabel")}
      htmlFor="trigger-overlap"
      description={t(`overlapHint.${value}`)}
    >
      <Select value={value} onValueChange={(next) => onChange(next as TriggerOverlap)}>
        <SelectTrigger id="trigger-overlap">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {POLICIES.map((policy) => (
            <SelectItem key={policy} value={policy}>
              {t(`overlap.${policy}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
