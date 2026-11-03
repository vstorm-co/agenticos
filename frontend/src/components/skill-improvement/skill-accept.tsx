"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { ContinueSession } from "@/components/improvement/continue-session";
import { useReadOnly } from "@/components/improvement/read-only";
import { Button, Checkbox, Input, Label } from "@/components/ui";
import { useSkillAccept } from "@/hooks/use-skill-improvement";
import { useReturnToMain } from "@/hooks/use-skill-merge";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import type { CheckOutcome, SkillCheck } from "@/types/skill-checks";
import type { MergeOutcome, SkillImprovement } from "@/types/skill-improvement";
import { AddTestQuestions } from "./add-test-questions";
import { CheckAgain } from "./check-again";

/**
 * Whether a decision was refused because the line got a newer version or new agents
 * since the check - the refusals Check again answers. Other 409s, such as a check
 * decided elsewhere, are only said.
 */
function movedLine(failure: unknown): boolean {
  return (
    failure instanceof ApiError &&
    failure.code === "CONCURRENT_CHANGE" &&
    (failure.details?.version !== undefined || failure.details?.agents !== undefined)
  );
}

/** The outcomes that change the skill, each held until the person confirms it. */
const WRITES: (CheckOutcome | MergeOutcome)[] = [
  "apply",
  "apply_and_pin",
  "fork_for_helped",
  "catch_up",
  "return_to_main",
];

/**
 * What to do with a measured attempt. The check decides what may be done: applying
 * when nobody is worse, pinning the agents it made worse or forking it for the ones
 * it helped when somebody is, improving further, or discarding it. A reader who may
 * not edit the skill sees the verdict and none of the decisions. A result whose line or
 * agents moved since its check offers Check again in place of the decisions it no longer
 * backs. A catch-up takes the merge into the fork, or - when main alone made nobody worse
 * - returns the fork's agents to main instead.
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
  const tImprovement = useTranslations("improvement");
  const locale = useLocale();
  const readOnly = useReadOnly();
  const { apply, fork } = useSkillAccept(session.skill_id, session.id);
  const returnToMain = useReturnToMain(session.skill_id, session.id);
  const busy = apply.isPending || fork.isPending || returnToMain.isPending;
  const catchUp = session.purpose === "catch_up";
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const names = (state: string) =>
    list.format(check.agents.filter((row) => row.state === state).map((row) => row.agent.name));
  const unknown =
    check.agents.filter((row) => row.state === "unknown").length + check.hidden_unknown;
  const unknownNames = names("unknown");
  const helped = check.agents.find((row) => row.state === "better");
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [forkName, setForkName] = useState(helped?.agent.name ?? "");
  const [refusal, setRefusal] = useState<string | null>(null);
  const [lineMoved, setLineMoved] = useState(false);
  const blockedOnFork =
    check.verdict === "blocked" &&
    session.fork_id !== null &&
    !session.outcomes.includes("apply_and_pin") &&
    !session.outcomes.includes("fork_for_helped");
  const writes = session.outcomes.some((outcome) => WRITES.includes(outcome));
  const held = !confirmed || (unknown > 0 && !acknowledged);
  const recheck = session.stale === true || lineMoved;

  async function decide(write: () => Promise<unknown>) {
    setRefusal(null);
    try {
      await write();
    } catch (failure) {
      if (movedLine(failure)) setLineMoved(true);
      setRefusal(getErrorMessage(failure, tErrors));
    }
  }
  const applyIt = (pinWorse: boolean) =>
    decide(() => apply.mutateAsync({ acknowledge_unknown: acknowledged, pin_worse: pinWorse }));

  const decisions = (
    <>
      {session.outcomes.includes("apply") && (
        <Button disabled={held} loading={busy} onClick={() => void applyIt(false)}>
          {t("apply", { line: session.line_name })}
        </Button>
      )}
      {session.outcomes.includes("apply_and_pin") && (
        <Button variant="outline" disabled={held} loading={busy} onClick={() => void applyIt(true)}>
          {t("applyAndPin", { names: names("worse") })}
        </Button>
      )}
      {session.outcomes.includes("catch_up") && (
        <Button disabled={held} loading={busy} onClick={() => void applyIt(false)}>
          {t("catchUp", { line: session.line_name })}
        </Button>
      )}
      {session.outcomes.includes("return_to_main") && (
        <Button
          variant="outline"
          disabled={held}
          loading={busy}
          onClick={() => void decide(() => returnToMain.mutateAsync())}
        >
          {t("returnToMain", { line: session.line_name })}
        </Button>
      )}
    </>
  );

  return (
    <section className="space-y-4 rounded-xl border p-6" data-tour="skill-improvement-accept">
      <h2 className="font-medium">{t("title")}</h2>
      {check.verdict !== null && (
        <p className="text-sm">{t(`${catchUp ? "catchUpVerdict" : "verdict"}.${check.verdict}`)}</p>
      )}
      {check.warnings.map((warning) => (
        <p key={warning} className="text-warning text-sm">
          {t(`warning.${warning}`)}
        </p>
      ))}
      {blockedOnFork && <p className="text-muted-foreground text-sm">{t("forkLineOnly")}</p>}
      {readOnly ? null : (
        <>
          {!recheck && unknown > 0 && (
            <div className="space-y-2 rounded-lg border p-3">
              <div className="flex items-start gap-2">
                <Checkbox
                  id="skill-accept-unknown"
                  checked={acknowledged}
                  onCheckedChange={(checked) => setAcknowledged(checked === true)}
                />
                <Label htmlFor="skill-accept-unknown" className="leading-snug font-normal">
                  {t("acknowledge", {
                    count: unknown,
                    names: unknownNames,
                    named: unknownNames === "" ? "no" : "yes",
                  })}
                </Label>
              </div>
              <AddTestQuestions skillId={session.skill_id} />
            </div>
          )}
          {!recheck && writes && (
            <div className="flex items-start gap-2">
              <Checkbox
                id="skill-accept-confirm"
                checked={confirmed}
                onCheckedChange={(checked) => setConfirmed(checked === true)}
              />
              <Label htmlFor="skill-accept-confirm" className="leading-snug font-normal">
                {tImprovement("confirmation")}
              </Label>
            </div>
          )}
          {!recheck && session.outcomes.includes("fork_for_helped") && helped && (
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
                loading={busy}
                onClick={() =>
                  void decide(() =>
                    fork.mutateAsync({ name: forkName.trim(), acknowledge_unknown: acknowledged }),
                  )
                }
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
          {recheck && <CheckAgain session={session} onStarted={onStarted} />}
          <ContinueSession
            session={session}
            lead={recheck ? undefined : decisions}
            emphasis={{ again: "outline", end: "ghost" }}
            onStarted={onStarted}
          />
        </>
      )}
    </section>
  );
}
