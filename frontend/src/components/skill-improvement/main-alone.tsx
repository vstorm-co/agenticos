"use client";

import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { Checkbox, Label } from "@/components/ui";
import type { ContinuationEstimate } from "@/types/improvement";
import type { SkillCheck } from "@/types/skill-checks";
import type { SkillContinuationEstimate, SkillImprovement } from "@/types/skill-improvement";
import { CheckAgents } from "./check-agents";

/**
 * Under a catch-up's check price: whether to also check main's newest version alone on
 * the fork's agents, priced on its own line. Only that check can show the fork is no
 * longer needed, so turning it off takes Return to main off the result.
 */
export function MainAloneChoice({
  quote,
  checked,
  onChange,
}: {
  quote: ContinuationEstimate;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const t = useTranslations("skillImprovement.mainAlone");
  const locale = useLocale();
  const price = (quote as SkillContinuationEstimate).main_alone_usd;
  return (
    <div className="flex items-start gap-2">
      <Checkbox
        id="skill-main-alone"
        checked={checked}
        onCheckedChange={(next) => onChange(next === true)}
      />
      <Label htmlFor="skill-main-alone" className="leading-snug font-normal">
        {price ? t("choicePriced", { cost: usd(price, locale) }) : t("choice")}
        <span className="text-muted-foreground block text-xs">{t("choiceWhy")}</span>
      </Label>
    </div>
  );
}

/** A catch-up's second check, or why there is none, beside the merge's own. */
export function MainAloneResult({ session }: { session: SkillImprovement }) {
  const t = useTranslations("skillImprovement.mainAlone");
  if (session.purpose !== "catch_up" || !session.main_alone) return null;
  return (
    <section aria-label={t("title")} className="space-y-2">
      <h3 className="text-sm font-medium">{t("title")}</h3>
      {session.main_alone_check ? (
        <CheckAgents check={session.main_alone_check} />
      ) : (
        <p className="text-muted-foreground text-sm">{t(`none.${session.main_alone}`)}</p>
      )}
    </section>
  );
}

/** How many agents a check could not measure, the hidden ones included. */
export function unmeasured(check: SkillCheck | null | undefined): number {
  if (!check) return 0;
  return check.agents.filter((row) => row.state === "unknown").length + check.hidden_unknown;
}

/**
 * Before returning a fork's agents to main: main alone could not be checked on some of
 * them, so they go only once a person says they know.
 */
export function MainAloneAcknowledge({
  check,
  checked,
  onChange,
}: {
  check: SkillCheck;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const t = useTranslations("skillImprovement.mainAlone");
  const locale = useLocale();
  const names = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    check.agents.filter((row) => row.state === "unknown").map((row) => row.agent.name),
  );
  return (
    <div className="flex items-start gap-2 rounded-lg border p-3">
      <Checkbox
        id="skill-return-unknown"
        checked={checked}
        onCheckedChange={(next) => onChange(next === true)}
      />
      <Label htmlFor="skill-return-unknown" className="leading-snug font-normal">
        {t("acknowledge", {
          count: unmeasured(check),
          names,
          named: names === "" ? "no" : "yes",
        })}
      </Label>
    </div>
  );
}
