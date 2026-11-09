"use client";

import { useState } from "react";
import { ChevronRight, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Card,
  CardContent,
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ContextHelp } from "@/components/ui/context-help";
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
  const [expanded, setExpanded] = useState(true);
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
    // A card of its own, beside the instructions rather than boxed inside them.
    <Card>
      <details
        className="group"
        open={expanded}
        onToggle={(event) => setExpanded(event.currentTarget.open)}
      >
        <summary className="focus-visible:outline-ring flex cursor-pointer list-none items-center gap-2 rounded-xl px-4 py-3 text-sm font-medium focus-visible:outline-2 [&::-webkit-details-marker]:hidden">
          <ChevronRight
            className="size-4 shrink-0 transition-transform group-open:rotate-90"
            aria-hidden
          />
          {t("variablesTitle")}
          {custom.length > 0 && (
            <span className="text-muted-foreground ml-auto tabular-nums">{custom.length}</span>
          )}
        </summary>
        <CardContent className="space-y-3 px-4 pb-4">
          <div className="flex items-center gap-2">
            <p className="text-muted-foreground flex-1 text-xs">{t("variablesHint")}</p>
            <ContextHelp>{t("variableNameRule")}</ContextHelp>
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
                <li
                  key={variable.name}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[9rem_minmax(0,1fr)_auto]"
                >
                  <span className="min-w-0 truncate font-mono text-xs">{variable.name}</span>
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
                    className="order-3 col-span-2 h-8 min-w-0 text-base sm:order-none sm:col-span-1 sm:text-sm"
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
            <div className="w-full space-y-1 sm:w-auto">
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
                className="h-8 w-full font-mono text-base sm:w-40 sm:text-sm"
              />
            </div>
            <div className="w-full min-w-0 flex-1 space-y-1 sm:w-auto sm:min-w-40">
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
            <Select
              value={zoneMode}
              disabled={disabled}
              onValueChange={(value) => onTimeZoneChange(value === "chosen" ? "UTC" : value)}
            >
              <SelectTrigger
                id="variables-time-zone"
                className="h-8 w-full min-w-0 sm:w-auto sm:min-w-56"
              >
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="system">{t("timeZoneSystem")}</SelectItem>
                <SelectItem value="user">{t("timeZoneUser")}</SelectItem>
                <SelectItem value="chosen">{t("timeZoneChosen")}</SelectItem>
              </SelectContent>
            </Select>
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
        </CardContent>
      </details>
    </Card>
  );
}
