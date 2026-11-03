"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Checkbox, Label } from "@/components/ui";
import type { SkillCheck, SkillCheckApply } from "@/types/skill-checks";

/**
 * What a finished check allows. Agents that could not be checked are acknowledged
 * before applying; a change that made agents worse is applied only with them kept
 * on the version they read now.
 */
export function CheckDecision({
  check,
  busy,
  onApply,
  onDiscard,
}: {
  check: SkillCheck;
  busy: boolean;
  onApply: (body: SkillCheckApply) => void;
  onDiscard: () => void;
}) {
  const t = useTranslations("skills.check");
  const [acknowledged, setAcknowledged] = useState(false);
  const unknown = check.agents.some((row) => row.state === "unknown") || check.hidden_unknown > 0;
  const pin = check.outcomes.includes("apply_and_pin");
  const apply = check.outcomes.includes("apply") || pin;
  return (
    <div className="space-y-3">
      <p className="text-sm">{t(`verdict.${check.verdict}`)}</p>
      {check.warnings.length > 0 && <p className="text-muted-foreground text-xs">{t("noisy")}</p>}
      {check.verdict === "blocked" && !pin && (
        <p className="text-muted-foreground text-xs">{t("forkLine")}</p>
      )}
      {apply && unknown && (
        <div className="flex items-center gap-2">
          <Checkbox
            id="acknowledge-unknown"
            checked={acknowledged}
            onCheckedChange={(value) => setAcknowledged(value === true)}
          />
          <Label htmlFor="acknowledge-unknown" className="text-xs">
            {t("acknowledge")}
          </Label>
        </div>
      )}
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" disabled={busy} onClick={onDiscard}>
          {t("discard")}
        </Button>
        {apply && (
          <Button
            disabled={busy || (unknown && !acknowledged)}
            onClick={() => onApply({ acknowledge_unknown: acknowledged, pin_worse: pin })}
          >
            {pin ? t("applyAndPin") : t("apply")}
          </Button>
        )}
      </div>
    </div>
  );
}
