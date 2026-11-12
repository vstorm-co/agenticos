"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ForkDialog } from "@/components/skill-improvement/fork-dialog";
import { Button, Checkbox, ConfirmDialog, Label } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { SkillCheck, SkillCheckApply, SkillCheckFork } from "@/types/skill-checks";

/**
 * What a finished check allows, exactly as the check offers it. Agents that could
 * not be checked are acknowledged before applying or forking; a change that made
 * agents worse is applied only with them kept on the version they read now.
 * Improving further goes back to the text - in the editor that wrote it, when there
 * is one - and discarding asks first, since the change cannot be decided again.
 */
export function CheckDecision({
  check,
  busy,
  onApply,
  onFork,
  onDiscard,
  onEdit,
}: {
  check: SkillCheck;
  busy: boolean;
  onApply: (body: SkillCheckApply) => void;
  /** Resolves to why the fork was refused, or null once it was made. */
  onFork: (body: SkillCheckFork) => Promise<string | null>;
  onDiscard: () => void;
  /** Back to editing the checked text; without it, improving further is a new session. */
  onEdit?: () => void;
}) {
  const t = useTranslations("skills.check");
  const [acknowledged, setAcknowledged] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const offers = (outcome: SkillCheck["outcomes"][number]) => check.outcomes.includes(outcome);
  const unknown = check.agents.some((row) => row.state === "unknown") || check.hidden_unknown > 0;
  const pin = offers("apply_and_pin");
  const apply = offers("apply") || pin;
  const fork = offers("fork_for_helped");
  const waiting = unknown && !acknowledged;
  const line = check.line.fork_id;
  return (
    <div className="space-y-3">
      <p className="text-sm">
        {check.no_readers ? t("verdict.noReaders") : t(`verdict.${check.verdict}`)}
      </p>
      {check.warnings.length > 0 && <p className="text-muted-foreground text-xs">{t("noisy")}</p>}
      {check.verdict === "blocked" && !pin && (
        <p className="text-muted-foreground text-xs">{t("forkLine")}</p>
      )}
      {(apply || fork) && unknown && (
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
        {offers("discard") && (
          <Button variant="ghost" disabled={busy} onClick={() => setDiscarding(true)}>
            {t("discard")}
          </Button>
        )}
        {offers("improve_further") &&
          (onEdit ? (
            <Button variant="outline" disabled={busy} onClick={onEdit}>
              {t("backToEditing")}
            </Button>
          ) : busy ? (
            <Button variant="outline" disabled>
              {t("improveFurther")}
            </Button>
          ) : (
            <Button variant="outline" asChild>
              <Link
                href={`${ROUTES.SKILL_DETAIL(check.skill_id)}/improve/new${line === null ? "" : `?fork=${line}`}`}
              >
                {t("improveFurther")}
              </Link>
            </Button>
          ))}
        {fork && (
          <ForkDialog
            skillId={check.skill_id}
            check={check}
            attempt={1}
            disabled={busy || waiting}
            busy={busy}
            onFork={(choice) => onFork({ ...choice, acknowledge_unknown: acknowledged })}
          />
        )}
        {apply && (
          <Button
            disabled={busy || waiting}
            onClick={() => onApply({ acknowledge_unknown: acknowledged, pin_worse: pin })}
          >
            {pin ? t("applyAndPin") : t("apply")}
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={discarding}
        onOpenChange={setDiscarding}
        title={t("discardConfirm.title")}
        description={t("discardConfirm.description")}
        confirmLabel={t("discard")}
        destructive
        loading={busy}
        onConfirm={() => {
          setDiscarding(false);
          onDiscard();
        }}
      />
    </div>
  );
}
