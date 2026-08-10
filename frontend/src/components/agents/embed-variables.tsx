"use client";

import { Plus, X } from "lucide-react";

import { Button, Checkbox, Input, Label } from "@/components/ui";
import type { EmbedVariable } from "@/types/embeds";
import { useTranslations } from "next-intl";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_NAME = 64;
const MAX_DESCRIPTION = 200;
const MAX_VARIABLES = 20;

/**
 * What the page must tell this widget about the visitor in front of it.
 *
 * The placement context beside it is one sentence, the same for everybody -
 * *you are on the pricing page*. This is the part only the integrator knows:
 * which plan somebody is on, which order they are looking at. Each row is a
 * name the page supplies, a flag saying whether the agent is expected to have
 * it, and a line for whoever writes the integration.
 *
 * The name is the contract, so it is the only field that is required and the
 * only one with a shape: it is written into a prompt and read back by a person,
 * never evaluated. Anything the page sends that is not declared here is dropped
 * server-side - the page is something a visitor can edit, and without a
 * declaration any key they invented would become a line in the agent's
 * instructions.
 */
export function EmbedVariables({
  variables,
  disabled,
  onChange,
}: {
  variables: EmbedVariable[];
  disabled: boolean;
  onChange: (variables: EmbedVariable[]) => void;
}) {
  const t = useTranslations("agents");

  function edit(index: number, patch: Partial<EmbedVariable>) {
    onChange(variables.map((row, at) => (at === index ? { ...row, ...patch } : row)));
  }

  return (
    <div className="space-y-2">
      <Label>{t("whatThePageSupplies")}</Label>
      {variables.map((variable, index) => (
        <div key={index} className="flex items-start gap-2">
          <Input
            value={variable.name}
            onChange={(event) =>
              // Lower case, digits and underscores - the shape the backend
              // accepts. Corrected as it is typed rather than refused on save,
              // because the rule is invisible until it refuses.
              edit(index, {
                name: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"),
              })
            }
            placeholder={t("variableNamePlaceholder")}
            aria-label={t("variableName", { index: index + 1 })}
            className="w-40 font-mono"
            maxLength={MAX_NAME}
            disabled={disabled}
          />
          <Input
            value={variable.description}
            onChange={(event) => edit(index, { description: event.target.value })}
            placeholder={t("variableDescriptionPlaceholder")}
            aria-label={t("variableDescription", { index: index + 1 })}
            maxLength={MAX_DESCRIPTION}
            disabled={disabled}
          />
          <Label className="flex shrink-0 items-center gap-1.5 py-2 text-xs font-normal">
            <Checkbox
              checked={variable.required}
              disabled={disabled}
              onCheckedChange={(checked) => edit(index, { required: checked === true })}
            />
            {t("variableRequired")}
          </Label>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            aria-label={t("removeVariable", { name: variable.name || String(index + 1) })}
            onClick={() => onChange(variables.filter((_, at) => at !== index))}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      ))}
      {variables.length < MAX_VARIABLES && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => onChange([...variables, { name: "", required: false, description: "" }])}
        >
          <Plus className="h-3.5 w-3.5" />
          {t("addVariable")}
        </Button>
      )}
      <p className="text-muted-foreground text-xs">{t("whatThePageSuppliesHint")}</p>
    </div>
  );
}
