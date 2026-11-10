"use client";

import { useId } from "react";
import { Check, CircleCheck, CircleX } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import type { AnswerAs } from "./dataset-target-fields";

export function AnswerPurpose({
  value,
  onChange,
}: {
  value: AnswerAs;
  onChange: (value: AnswerAs) => void;
}) {
  const t = useTranslations("datasets");
  const name = useId();
  const choices = [
    { value: "reference_answer", icon: CircleCheck, hint: "referencePurpose" },
    { value: "counter_example", icon: CircleX, hint: "counterPurpose" },
  ] as const;
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">{t("keepAnswerAs")}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {choices.map((choice) => (
          <label
            key={choice.value}
            className={cn(
              "has-focus-visible:ring-ring relative flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors has-focus-visible:ring-2",
              value === choice.value ? "border-foreground/40 bg-accent" : "hover:bg-accent/50",
            )}
          >
            <input
              type="radio"
              name={name}
              className="sr-only"
              value={choice.value}
              checked={value === choice.value}
              onChange={() => onChange(choice.value)}
            />
            <choice.icon className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 space-y-1">
              <span className="block text-sm font-medium">{t(`field.${choice.value}`)}</span>
              <span className="text-muted-foreground block text-xs">{t(choice.hint)}</span>
            </span>
            <Check
              className={cn("mt-0.5 size-4 shrink-0", value !== choice.value && "invisible")}
              aria-hidden
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}
