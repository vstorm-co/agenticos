"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ContinueSession } from "@/components/improvement/continue-session";
import { Button, Checkbox, Input, Label } from "@/components/ui";
import { useSkillAccept } from "@/hooks/use-skill-improvement";
import { getErrorMessage } from "@/lib/api-error";
import type { SkillCheck } from "@/types/skill-checks";
import type { SkillAcceptOutcome, SkillImprovement } from "@/types/skill-improvement";
import { AddTestQuestions } from "./add-test-questions";

/**
 * What to do with a measured attempt. The check decides what may be done: applying
 * when nobody is worse, pinning the agents it made worse or forking it for the ones
 * it helped when somebody is, improving further, or discarding it.
 */
export function SkillAccept({
  session,
  check,
  onStarted,
}: {
  session: SkillImprovement;
  check: SkillCheck;
  onStarted: () => void;
}) {
  const t = useTranslations("skillImprovement.accept");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const accept = useSkillAccept(session.skill_id, session.id);
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const names = (state: string) =>
    list.format(check.agents.filter((row) => row.state === state).map((row) => row.agent.name));
  const unknown =
    check.agents.filter((row) => row.state === "unknown").length + check.hidden_unknown;
  const helped = check.agents.find((row) => row.state === "better");
  const [acknowledged, setAcknowledged] = useState(false);
  const [forkName, setForkName] = useState(helped?.agent.name ?? "");
  const [refusal, setRefusal] = useState<string | null>(null);
  const blockedOnFork =
    check.verdict === "blocked" &&
    session.fork_id !== null &&
    !check.outcomes.includes("apply_and_pin") &&
    !check.outcomes.includes("fork_for_helped");
  const held = unknown > 0 && !acknowledged;

  async function decide(outcome: SkillAcceptOutcome) {
    setRefusal(null);
    try {
      await accept.mutateAsync({
        outcome,
        acknowledge_unknown: acknowledged,
        ...(outcome === "fork_for_helped" ? { fork_name: forkName.trim() } : {}),
      });
    } catch (failure) {
      setRefusal(getErrorMessage(failure, tErrors));
    }
  }

  const decisions = (
    <>
      {check.outcomes.includes("apply") && (
        <Button disabled={held} loading={accept.isPending} onClick={() => void decide("apply")}>
          {t("apply", { line: session.line_name })}
        </Button>
      )}
      {check.outcomes.includes("apply_and_pin") && (
        <Button
          variant="outline"
          disabled={held}
          loading={accept.isPending}
          onClick={() => void decide("apply_and_pin")}
        >
          {t("applyAndPin", { names: names("worse") })}
        </Button>
      )}
    </>
  );

  return (
    <section className="space-y-4 rounded-xl border p-6" data-tour="skill-improvement-accept">
      <h2 className="font-medium">{t("title")}</h2>
      {check.verdict !== null && <p className="text-sm">{t(`verdict.${check.verdict}`)}</p>}
      {check.warnings.map((warning) => (
        <p key={warning} className="text-warning text-sm">
          {t(`warning.${warning}`)}
        </p>
      ))}
      {blockedOnFork && <p className="text-muted-foreground text-sm">{t("forkLineOnly")}</p>}
      {unknown > 0 && (
        <div className="space-y-2 rounded-lg border p-3">
          <div className="flex items-start gap-2">
            <Checkbox
              id="skill-accept-unknown"
              checked={acknowledged}
              onCheckedChange={(checked) => setAcknowledged(checked === true)}
            />
            <Label htmlFor="skill-accept-unknown" className="leading-snug font-normal">
              {t("acknowledge", { count: unknown, names: names("unknown") })}
            </Label>
          </div>
          <AddTestQuestions skillId={session.skill_id} />
        </div>
      )}
      {check.outcomes.includes("fork_for_helped") && helped && (
        <div className="max-w-md space-y-2">
          <Label htmlFor="skill-accept-fork">{t("forkName")}</Label>
          <Input
            id="skill-accept-fork"
            value={forkName}
            maxLength={64}
            onChange={(event) => setForkName(event.target.value)}
          />
          <Button
            variant="outline"
            disabled={held || forkName.trim() === ""}
            loading={accept.isPending}
            onClick={() => void decide("fork_for_helped")}
          >
            {t("forkForHelped", { names: names("better") })}
          </Button>
        </div>
      )}
      {refusal !== null && (
        <p role="alert" className="text-destructive text-sm">
          {refusal}
        </p>
      )}
      <ContinueSession
        session={session}
        lead={decisions}
        emphasis={{ again: "outline", end: "ghost" }}
        onStarted={onStarted}
      />
    </section>
  );
}
