"use client";

import { useTranslations } from "next-intl";

import { Input, Label, Switch } from "@/components/ui";
import type { LoopGuardSpec } from "@/types/agents";

/** The defaults the server applies to an agent that never set them. */
export const LOOP_GUARD_DEFAULTS: LoopGuardSpec = { enabled: true, repeats: 4, cycles: 3 };

/**
 * When a run that loops on its tool calls is warned, then stopped (#2086).
 *
 * Beside the step limit, because both answer "how does a run that is getting
 * nowhere end": this one sooner, with the reason, before the steps run out.
 */
export function LoopGuardFields({
  value,
  onChange,
  disabled,
}: {
  value: LoopGuardSpec | undefined;
  onChange: (value: LoopGuardSpec) => void;
  disabled: boolean;
}) {
  const t = useTranslations("pages.agents");
  const guard = value ?? LOOP_GUARD_DEFAULTS;
  const set = (key: "repeats" | "cycles", raw: string, fallback: number) =>
    onChange({ ...guard, [key]: raw ? Number(raw) : fallback });
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <Label htmlFor="loop-guard">{t("loopGuard")}</Label>
          <p id="loop-guard-hint" className="text-muted-foreground mt-1 text-xs">
            {t("loopGuardHint")}
          </p>
        </div>
        <Switch
          id="loop-guard"
          checked={guard.enabled}
          disabled={disabled}
          aria-describedby="loop-guard-hint"
          onCheckedChange={(enabled) => onChange({ ...guard, enabled })}
        />
      </div>
      {guard.enabled && (
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="loop-repeats">{t("loopRepeats")}</Label>
            <Input
              id="loop-repeats"
              type="number"
              min="2"
              max="20"
              value={guard.repeats}
              disabled={disabled}
              onChange={(event) => set("repeats", event.target.value, LOOP_GUARD_DEFAULTS.repeats)}
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="loop-cycles">{t("loopCycles")}</Label>
            <Input
              id="loop-cycles"
              type="number"
              min="2"
              max="10"
              value={guard.cycles}
              disabled={disabled}
              onChange={(event) => set("cycles", event.target.value, LOOP_GUARD_DEFAULTS.cycles)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
