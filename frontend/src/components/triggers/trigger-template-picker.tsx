"use client";

import { useTranslations } from "next-intl";

import { EventSourceMark } from "@/components/triggers/event-source-mark";
import { Label } from "@/components/ui";
import { useTriggerTemplates } from "@/hooks";
import { templateIcon } from "@/lib/trigger-template-icons";
import { cn } from "@/lib/utils";
import type { TriggerTemplate } from "@/types/trigger-templates";
import type { EventSource, TriggerType } from "@/types/triggers";

interface TriggerTemplatePickerProps {
  /** Which flow's cards to offer - a template never crosses modes. */
  triggerType: TriggerType;
  /** For the event flow, only this source's templates fit the message step. */
  eventSource?: EventSource;
  /** The key of the picked template, or null when starting from scratch. */
  selectedKey: string | null;
  /** Picking a template prefills what its mode can use in the form around it. */
  onPick: (template: TriggerTemplate) => void;
  /** Starting from scratch clears the prefill and leaves the form blank. */
  onScratch: () => void;
}

/**
 * The seeded trigger templates, offered before the blank prompt.
 *
 * A first trigger is otherwise an empty box; a template turns it into a pick
 * that prefills the message (and, for a schedule, the cadence), still editable
 * below. The catalog carries both modes, so the picker filters to the flow it
 * sits in: every schedule template on the New-schedule flow, one source's event
 * templates on that source's message step - a prompt written for a GitHub issue
 * makes no sense against an inbound email. "Start from scratch" stays for the
 * case a template does not cover. Nothing is shown while the catalog loads or
 * when nothing fits - the flow then just opens on the blank form it always had.
 */
export function TriggerTemplatePicker({
  triggerType,
  eventSource,
  selectedKey,
  onPick,
  onScratch,
}: TriggerTemplatePickerProps) {
  const t = useTranslations("triggers");
  const { templates, isLoading } = useTriggerTemplates();

  const offered = templates.filter((template) =>
    triggerType === "schedule"
      ? template.trigger_type === "schedule"
      : template.trigger_type === "event" && template.event_source === eventSource,
  );

  if (isLoading || offered.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <Label>{t("templatesLabel")}</Label>
      <div className="grid gap-2 sm:grid-cols-2">
        {offered.map((template) => {
          const active = template.key === selectedKey;
          const Glyph = templateIcon(template.key);
          return (
            <button
              key={template.key}
              type="button"
              onClick={() => onPick(template)}
              aria-pressed={active}
              className={cn(
                "flex items-start gap-2.5 rounded-md border p-2.5 text-left transition-colors",
                active
                  ? "border-foreground/30 bg-accent"
                  : "border-input hover:border-foreground/30",
              )}
            >
              {/* An event template wears its source's brand mark and a schedule
                    one a glyph for what it does - decorative either way, since the
                    label sits beside it. */}
              <span className="text-muted-foreground mt-0.5 shrink-0" aria-hidden>
                {template.event_source ? (
                  <EventSourceMark source={template.event_source} className="h-4 w-4" />
                ) : (
                  <Glyph className="h-4 w-4" />
                )}
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-medium">{template.label}</span>
                <span className="text-muted-foreground block text-xs">{template.description}</span>
              </span>
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
          <p className="text-muted-foreground text-xs">
            {triggerType === "schedule" ? t("templateScratchHelp") : t("templateScratchHelpEvent")}
          </p>
        </button>
      </div>
    </div>
  );
}
