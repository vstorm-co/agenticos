"use client";

import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { useEvalSuites } from "@/hooks/use-eval-suites";
import { usePermissions } from "@/hooks/use-permissions";
import type { EvalSuite, EvalSuitePin } from "@/types/eval-suites";
import { Perm } from "@/types/permissions";

/** Whether the dataset moved on since the guard was pinned to it - unknown to a reader who cannot see it. */
function behind(pin: EvalSuitePin): boolean {
  if (pin.latest_dataset_version === null) return false;
  return pin.dataset_version !== pin.latest_dataset_version || pin.scoring_current === false;
}

/** A guard's pin, short, for its row: amber once the dataset has moved on, or with none yet. */
export function SuitePinBadge({ suite }: { suite: EvalSuite }) {
  const t = useTranslations("evals.suites.pin");
  if (suite.pin === null) return null;
  if (suite.pin.dataset_version === null) {
    return <Badge variant="warning">{t("unpinnedBadge")}</Badge>;
  }
  return (
    <Badge variant={behind(suite.pin) ? "warning" : "outline"}>
      {t("badge", { version: suite.pin.dataset_version })}
    </Badge>
  );
}

/** Pinning or moving the pin, for whoever may override promotions; disabled, with why, for the rest. */
function PinAction({ suite, label }: { suite: EvalSuite; label: string }) {
  const t = useTranslations("evals.suites.pin");
  const { can } = usePermissions();
  const { movePin } = useEvalSuites(suite.agent_id);
  const allowed = can(Perm.promotionsOverride);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        disabled={!allowed || movePin.isPending}
        onClick={() => movePin.mutate(suite.id)}
      >
        {label}
      </Button>
      {!allowed && <span className="text-muted-foreground">{t("needsOverride")}</span>}
    </div>
  );
}

/**
 * What a guard checks, against what its dataset holds now.
 *
 * Editing the dataset does not move a guard, so a guard can fall behind it; only
 * somebody who may override promotions moves it on, and everybody else is told
 * why they cannot.
 */
export function SuitePin({ suite }: { suite: EvalSuite }) {
  const t = useTranslations("evals.suites.pin");
  const pin = suite.pin;
  if (pin === null) return null;
  const latest = pin.latest_dataset_version;
  if (pin.dataset_version === null) {
    return (
      <div className="space-y-1.5 border-b px-5 py-3 text-xs">
        <p>{t("unpinned")}</p>
        {latest !== null && latest > 0 && <PinAction suite={suite} label={t("move", { latest })} />}
      </div>
    );
  }
  if (latest === null) {
    return (
      <p className="border-b px-5 py-3 text-xs">{t("pinned", { pinned: pin.dataset_version })}</p>
    );
  }
  return (
    <div className="space-y-1.5 border-b px-5 py-3 text-xs">
      <p>
        {behind(pin)
          ? t("behind", { pinned: pin.dataset_version, latest })
          : t("current", { pinned: pin.dataset_version })}
      </p>
      {pin.scoring_current === false && (
        <p className="text-muted-foreground">{t("scoringChanged")}</p>
      )}
      {behind(pin) && <PinAction suite={suite} label={t("move", { latest })} />}
    </div>
  );
}
