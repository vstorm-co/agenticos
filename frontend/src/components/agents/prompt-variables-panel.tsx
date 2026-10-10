"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input, Label } from "@/components/ui";
import type { PromptVariableSpec, SystemPromptVariable } from "@/types/agents";

const NAME = /^[a-z][a-z0-9_]{0,39}$/;
const ZONES = Intl.supportedValuesOf("timeZone");

interface PromptVariablesPanelProps {
  system: SystemPromptVariable[];
  custom: PromptVariableSpec[];
  timeZone: string;
  disabled: boolean;
  onInsert: (name: string) => void;
  onCustomChange: (variables: PromptVariableSpec[]) => void;
  onTimeZoneChange: (zone: string) => void;
}

/**
 * What the instructions may say with `{{name}}`, under the editor (#2065).
 *
 * Every variable is a button that inserts it at the caret, with what it becomes
 * beside it; custom variables are defined right here; the time zone decides what
 * `{{current_time}}` says - the deployment's, each person's own, or one chosen.
 */
export function PromptVariablesPanel({
  system,
  custom,
  timeZone,
  disabled,
  onInsert,
  onCustomChange,
  onTimeZoneChange,
}: PromptVariablesPanelProps) {
  const t = useTranslations("agents");
  const [adding, setAdding] = useState({ name: "", value: "" });
  const taken = new Set([...system.map((v) => v.name), ...custom.map((v) => v.name)]);
  const nameProblem =
    adding.name === ""
      ? null
      : !NAME.test(adding.name)
        ? t("variableNameRule")
        : taken.has(adding.name)
          ? t("variableNameTaken")
          : null;
  const zoneMode = timeZone === "system" || timeZone === "user" ? timeZone : "chosen";

  const add = () => {
    onCustomChange([...custom, { name: adding.name, value: adding.value }]);
    setAdding({ name: "", value: "" });
  };

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div>
        <p className="text-sm font-medium">{t("variablesTitle")}</p>
        <p className="text-muted-foreground text-xs">{t("variablesHint")}</p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {[...system, ...custom].map((variable) => (
          <Button
            key={variable.name}
            type="button"
            size="sm"
            variant="outline"
            className="h-6 px-2 font-mono text-xs"
            disabled={disabled}
            title={variable.description ?? ""}
            onClick={() => onInsert(variable.name)}
          >
            {`{{${variable.name}}}`}
          </Button>
        ))}
      </div>

      {custom.length > 0 && (
        <ul className="space-y-2">
          {custom.map((variable, index) => (
            <li key={variable.name} className="flex items-center gap-2">
              <span className="w-36 shrink-0 truncate font-mono text-xs">{variable.name}</span>
              <Input
                aria-label={t("variableValueFor", { name: variable.name })}
                value={variable.value}
                disabled={disabled}
                onChange={(event) =>
                  onCustomChange(
                    custom.map((one, at) =>
                      at === index ? { ...one, value: event.target.value } : one,
                    ),
                  )
                }
                className="h-8 text-base sm:text-sm"
              />
              <Button
                type="button"
                size="icon"
                variant="ghost"
                aria-label={t("removePromptVariable", { name: variable.name })}
                disabled={disabled}
                onClick={() => onCustomChange(custom.filter((_, at) => at !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <div className="space-y-1">
          <Label htmlFor="new-variable-name" className="text-xs">
            {t("promptVariableName")}
          </Label>
          <Input
            id="new-variable-name"
            value={adding.name}
            disabled={disabled}
            placeholder={t("promptVariableNamePlaceholder")}
            aria-invalid={nameProblem !== null}
            onChange={(event) => setAdding({ ...adding, name: event.target.value })}
            className="h-8 w-40 font-mono text-base sm:text-sm"
          />
        </div>
        <div className="min-w-40 flex-1 space-y-1">
          <Label htmlFor="new-variable-value" className="text-xs">
            {t("variableValue")}
          </Label>
          <Input
            id="new-variable-value"
            value={adding.value}
            disabled={disabled}
            onChange={(event) => setAdding({ ...adding, value: event.target.value })}
            className="h-8 text-base sm:text-sm"
          />
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled || adding.name === "" || nameProblem !== null}
          onClick={add}
        >
          <Plus className="h-4 w-4" />
          {t("addPromptVariable")}
        </Button>
      </div>
      {nameProblem && <p className="text-destructive text-xs">{nameProblem}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor="variables-time-zone" className="text-xs">
          {t("timeZoneLabel")}
        </Label>
        <select
          id="variables-time-zone"
          value={zoneMode}
          disabled={disabled}
          onChange={(event) =>
            onTimeZoneChange(event.target.value === "chosen" ? "UTC" : event.target.value)
          }
          className="border-input h-8 rounded-md border bg-transparent px-2 text-base sm:text-sm"
        >
          <option value="system">{t("timeZoneSystem")}</option>
          <option value="user">{t("timeZoneUser")}</option>
          <option value="chosen">{t("timeZoneChosen")}</option>
        </select>
        {zoneMode === "chosen" && (
          <>
            <Input
              aria-label={t("timeZoneChosen")}
              list="variables-time-zones"
              value={timeZone}
              disabled={disabled}
              onChange={(event) => onTimeZoneChange(event.target.value)}
              className="h-8 w-56 text-base sm:text-sm"
            />
            <datalist id="variables-time-zones">
              {ZONES.map((zone) => (
                <option key={zone} value={zone} />
              ))}
            </datalist>
          </>
        )}
      </div>
    </div>
  );
}
