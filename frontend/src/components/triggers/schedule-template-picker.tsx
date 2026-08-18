"use client";

import { useTranslations } from "next-intl";

import { Label } from "@/components/ui";
import { useScheduleTemplates } from "@/hooks";
import { cn } from "@/lib/utils";
import type { ScheduleTemplate } from "@/types/schedule-templates";

interface ScheduleTemplatePickerProps {
  /** The key of the picked template, or null when starting from scratch. */
  selectedKey: string | null;
  /** Picking a template prefills the prompt and cadence in the form below. */
  onPick: (template: ScheduleTemplate) => void;
  /** Starting from scratch clears the prefill and leaves the form blank. */
  onScratch: () => void;
}

/**
 * The seeded schedule templates, offered before the blank prompt on a new
 * schedule.
 *
 * A first schedule is otherwise an empty box and a cron expression nobody wants to
 * write; a template turns it into a pick that prefills both the message and the
 * cadence, still editable below. "Start from scratch" stays for the case a
 * template does not cover. Nothing is shown while the catalog loads or when it is
 * empty - the flow then just opens on the blank form it always had.
 */
export function ScheduleTemplatePicker({
  selectedKey,
  onPick,
  onScratch,
}: ScheduleTemplatePickerProps) {
  const t = useTranslations("triggers");
  const { templates, isLoading } = useScheduleTemplates();

  if (isLoading || templates.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <Label>{t("templatesLabel")}</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {templates.map((template) => {
          const active = template.key === selectedKey;
          return (
            <button
              key={template.key}
              type="button"
              onClick={() => onPick(template)}
              aria-pressed={active}
              className={cn(
                "rounded-md border p-2.5 text-left transition-colors",
                active
                  ? "border-foreground/30 bg-accent"
                  : "border-input hover:border-foreground/30",
              )}
            >
              <p className="text-sm font-medium">{template.label}</p>
              <p className="text-muted-foreground text-xs">{template.description}</p>
            </button>
          );
        })}
        <button
          type="button"
          onClick={onScratch}
          aria-pressed={selectedKey === null}
          className={cn(
            "rounded-md border p-2.5 text-left transition-colors",
            selectedKey === null
              ? "border-foreground/30 bg-accent"
              : "border-input hover:border-foreground/30",
          )}
        >
          <p className="text-sm font-medium">{t("templateScratch")}</p>
          <p className="text-muted-foreground text-xs">{t("templateScratchHelp")}</p>
        </button>
      </div>
    </div>
  );
}
