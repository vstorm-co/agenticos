"use client";

import { useTranslations } from "next-intl";

import { Input, Label, Switch } from "@/components/ui";
import type { CodeModeSpec } from "@/types/agents";

/** The defaults the server applies to an agent that never set them. */
export const CODE_MODE_DEFAULTS: CodeModeSpec = { enabled: false, max_tool_calls: 100 };

/**
 * Whether the agent calls its tools from one sandboxed script (#2107).
 *
 * Beside the step limit, because it changes what a step is: one `run_code` turn
 * that makes many calls instead of a turn per call.
 */
export function CodeModeField({
  value,
  onChange,
  disabled,
}: {
  value: CodeModeSpec | undefined;
  onChange: (value: CodeModeSpec) => void;
  disabled: boolean;
}) {
  const t = useTranslations("agents");
  const mode = value ?? CODE_MODE_DEFAULTS;
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <Label htmlFor="code-mode">{t("codeMode")}</Label>
          <p id="code-mode-hint" className="text-muted-foreground mt-1 text-xs">
            {t("codeModeHint")}
          </p>
        </div>
        <Switch
          id="code-mode"
          checked={mode.enabled}
          disabled={disabled}
          aria-describedby="code-mode-hint"
          onCheckedChange={(enabled) => onChange({ ...mode, enabled })}
        />
      </div>
      {mode.enabled && (
        <div className="space-y-1.5">
          <Label htmlFor="code-mode-calls">{t("codeModeMaxCalls")}</Label>
          <Input
            id="code-mode-calls"
            type="number"
            min="1"
            max="500"
            value={mode.max_tool_calls}
            disabled={disabled}
            onChange={(event) =>
              onChange({
                ...mode,
                max_tool_calls: Number(event.target.value) || CODE_MODE_DEFAULTS.max_tool_calls,
              })
            }
          />
        </div>
      )}
    </div>
  );
}
