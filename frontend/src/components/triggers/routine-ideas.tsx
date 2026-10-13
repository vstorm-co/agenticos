"use client";

import { Clock } from "lucide-react";
import { useTranslations } from "next-intl";

import { useTriggerTemplates } from "@/hooks/use-trigger-templates";
import { templateIcon } from "@/lib/trigger-template-icons";
import { cadenceText } from "@/lib/trigger-format";
import type { TriggerTemplate } from "@/types/trigger-templates";

/**
 * Ready-made routines, offered on the page as things to start rather than only
 * inside the New schedule form.
 *
 * What Claude's and ChatGPT's scheduled pages lead with: an empty list says
 * "nothing yet", and the ideas under it say what this could be for - a morning
 * briefing, a weekly review - each with the cadence it would run on. Picking
 * one opens New schedule already filled in. The catalog is the backend's, the
 * same one the form's own picker reads, so the two cannot offer different
 * ideas.
 */
export function RoutineIdeas({ onPick }: { onPick: (template: TriggerTemplate) => void }) {
  const t = useTranslations("pages.routines");
  const tt = useTranslations("triggers");
  const { templates } = useTriggerTemplates();
  const ideas = templates.filter(
    (template) => template.trigger_type === "schedule" && template.suggested_cadence,
  );
  if (ideas.length === 0) return null;

  return (
    <section className="space-y-3" data-tour="routines-ideas">
      <div>
        <h2 className="text-sm font-semibold">{t("ideasTitle")}</h2>
        <p className="text-muted-foreground text-xs">{t("ideasHint")}</p>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {ideas.map((template) => {
          const Icon = templateIcon(template.key);
          const cadence = template.suggested_cadence!;
          return (
            <li key={template.key}>
              <button
                type="button"
                onClick={() => onPick(template)}
                className="border-border hover:border-foreground/25 hover:bg-accent/40 flex h-full w-full items-start gap-3 rounded-xl border p-3.5 text-left transition-colors"
              >
                <span className="bg-muted grid size-9 shrink-0 place-items-center rounded-lg">
                  <Icon className="text-foreground/70 h-4 w-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1 space-y-1">
                  <span className="block text-sm font-medium">{template.label}</span>
                  <span className="text-muted-foreground line-clamp-2 block text-xs">
                    {template.description}
                  </span>
                  <span className="text-muted-foreground flex items-center gap-1 text-xs">
                    <Clock className="h-3 w-3" aria-hidden />
                    {cadenceText(
                      {
                        trigger_type: "schedule",
                        schedule_kind: cadence.schedule_kind,
                        cron_expression: cadence.cron_expression ?? null,
                        interval_seconds: cadence.interval_seconds ?? null,
                      },
                      tt,
                    )}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
