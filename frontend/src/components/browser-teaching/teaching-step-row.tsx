"use client";

import { useTranslations } from "next-intl";

import { FormField, Input } from "@/components/ui";
import type { ReviewedStep, TeachingStep } from "@/lib/browser-teaching-api";

/** Steps whose value changes from case to case, so they may be named as a parameter. */
const PARAMETER_ACTIONS = new Set(["input_parameter", "select"]);

interface TeachingStepRowProps {
  step: TeachingStep;
  draft: ReviewedStep;
  disabled: boolean;
  onChange: (next: ReviewedStep) => void;
}

/**
 * One recorded step: what was done, on which kind of control and site, plus the
 * reviewer's own label and, for a typed or chosen value, a parameter name.
 *
 * No value from the page is shown or offered as a default. The step knows only
 * its action, the control's role and the origin.
 */
export function TeachingStepRow({ step, draft, disabled, onChange }: TeachingStepRowProps) {
  const t = useTranslations("browserTeaching");
  const action = step.human_step ? "human" : step.action;
  const labelId = `teaching-step-${step.sequence}-label`;
  const parameterId = `teaching-step-${step.sequence}-parameter`;
  const takesParameter = !step.human_step && PARAMETER_ACTIONS.has(step.action);

  return (
    <li className="space-y-3 px-4 py-4 sm:px-5" data-testid="teaching-step">
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-muted-foreground font-mono text-xs">{step.sequence}</span>
        <span className="text-sm font-medium">{t(`actions.${action}`)}</span>
        {step.target !== null && (
          <span className="text-muted-foreground text-xs">
            {t("onControl", { role: step.target.role })}
          </span>
        )}
        <span className="text-muted-foreground min-w-0 truncate font-mono text-xs">
          {step.origin}
        </span>
      </div>
      {!step.human_step && (
        <div className="grid gap-3 sm:grid-cols-2">
          <FormField htmlFor={labelId} label={t("label")}>
            <Input
              value={draft.label ?? ""}
              maxLength={80}
              disabled={disabled}
              onChange={(event) => onChange({ ...draft, label: event.target.value || null })}
            />
          </FormField>
          {takesParameter && (
            <FormField htmlFor={parameterId} label={t("parameter")}>
              <Input
                value={draft.parameter ?? ""}
                maxLength={40}
                disabled={disabled}
                className="font-mono"
                onChange={(event) =>
                  onChange({ ...draft, parameter: toParameterName(event.target.value) })
                }
              />
            </FormField>
          )}
        </div>
      )}
    </li>
  );
}

/** Lower case, letters, digits and underscores - the only parameter names the server takes. */
export function toParameterName(value: string): string | null {
  const name = value
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^[^a-z]+/, "");
  return name === "" ? null : name.slice(0, 40);
}
