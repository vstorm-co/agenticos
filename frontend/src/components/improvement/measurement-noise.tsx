"use client";

import Link from "next/link";
import { Check, Minus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useAgentsOfKind } from "@/hooks/use-agents";
import { ROUTES } from "@/lib/constants";
import type { Improvement, MeasurementNoise, NoisyAttempt } from "@/types/improvement";
import { Details } from "./widgets";

type Translate = ReturnType<typeof useTranslations>;

/** Why the test cannot tell the versions apart, as one plain sentence. */
export function noiseSentence(
  t: Translate,
  locale: string,
  noise: MeasurementNoise,
  agent: string,
  { note = false }: { note?: boolean } = {},
): string {
  const percent = (value: number) =>
    new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(value);
  const key = note ? "noise.note" : "noise.headline";
  return noise.baseline_low !== null && noise.baseline_high !== null && noise.baseline_spread > 0
    ? t(`${key}Spread`, {
        agent,
        low: percent(noise.baseline_low),
        high: percent(noise.baseline_high),
      })
    : t(`${key}Unstable`, { unstable: noise.unstable, heldOut: noise.held_out });
}

/**
 * Where the test is made reliable: its grading, its questions and its judge. The
 * rules a criterion's words suggest are offered under each criterion on the
 * dataset's grading tab, which this links to rather than reading the rubric here.
 */
export function NoiseActions({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.noise");
  const { agents } = useAgentsOfKind("judge");
  const judge = agents.find((agent) => agent.system_key != null);
  const dataset = ROUTES.DATASET_DETAIL(session.dataset_id);
  const grading = `${dataset}?tab=grading`;
  const fixes = [
    { key: "yesNo", href: grading, hint: t("yesNoHint") },
    {
      key: "checks",
      href: `${dataset}?tab=cases`,
      hint: t.rich("checksHint", {
        link: (chunks) => (
          <Link className="underline underline-offset-4" href={grading}>
            {chunks}
          </Link>
        ),
      }),
    },
    { key: "more", href: `${dataset}?tab=cases` },
    { key: "judge", href: judge ? ROUTES.AGENT_DETAIL(judge.id) : `${dataset}?tab=grading` },
  ];
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{t("fixTitle")}</p>
      <ul className="list-disc space-y-1.5 pl-5 text-sm">
        {fixes.map((fix) => (
          <li key={fix.key}>
            <Link className="underline underline-offset-4" href={fix.href}>
              {t(fix.key)}
            </Link>
            {fix.hint && <span className="text-muted-foreground block text-xs">{fix.hint}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The held-out questions graded differently without the agent changing, closed until opened. */
export function UnstableQuestions({ noise }: { noise: MeasurementNoise }) {
  const t = useTranslations("improvement.noise");
  if (noise.examples.length === 0) return null;
  return (
    <Details summary={t("unstableTitle", { count: noise.unstable })}>
      <ul className="space-y-3">
        {noise.examples.map((question) => (
          <li key={question.case_id} className="space-y-1 text-sm">
            <p className="break-words">{question.input}</p>
            {question.attempts.map((attempt) => (
              <AttemptGrades key={attempt.number} attempt={attempt} />
            ))}
          </li>
        ))}
      </ul>
    </Details>
  );
}

function AttemptGrades({ attempt }: { attempt: NoisyAttempt }) {
  const t = useTranslations("improvement.noise");
  return (
    <p className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span>{t("attempt", { number: attempt.number })}</span>
      <span className="inline-flex items-center gap-1">
        {t("today")} <Grades grades={attempt.baseline} />
      </span>
      <span className="inline-flex items-center gap-1">
        {t("changed")} <Grades grades={attempt.candidate} />
      </span>
    </p>
  );
}

function Grades({ grades }: { grades: (boolean | null)[] }) {
  const t = useTranslations("improvement.noise");
  return (
    <span className="inline-flex items-center">
      {grades.map((grade, index) => {
        const Icon = grade === null ? Minus : grade ? Check : X;
        return (
          <Icon
            key={index}
            role="img"
            aria-label={t(grade === null ? "notGraded" : grade ? "passed" : "failed")}
            className={
              grade === null
                ? "size-3.5"
                : grade
                  ? "text-success size-3.5"
                  : "text-destructive size-3.5"
            }
          />
        );
      })}
    </span>
  );
}
