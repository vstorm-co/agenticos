"use client";

import { useLocale, useTranslations } from "next-intl";

import { StepError } from "@/components/improvement/step-error";
import { useSkillProblems } from "@/hooks/use-skill-improvement";
import type { SkillImprovement, SkillProblem } from "@/types/skill-improvement";

/**
 * What went wrong in answers where the line's versions were loaded, one problem at
 * a time, each with the agents it occurs in. Answers from before loads were recorded
 * cannot be attributed, and are counted rather than guessed at.
 */
export function SkillUnderstand({ session }: { session: SkillImprovement }) {
  const t = useTranslations("skillImprovement.understand");
  const { problems, isLoading, error, refetch } = useSkillProblems(session.skill_id, session.id);
  if (error) return <StepError error={error} retry={refetch} />;
  if (isLoading || !problems) return <p role="status">{t("loading")}</p>;
  return (
    <section className="space-y-4" data-tour="skill-improvement-understand">
      <h2 className="font-medium">{t("title")}</h2>
      <p className="text-sm">
        {t("summary", {
          count: problems.problems.length,
          elsewhere: problems.not_the_skill,
          fine: problems.not_a_problem,
        })}
      </p>
      {problems.usage_unknown > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("usageUnknown", { count: problems.usage_unknown })}
        </p>
      )}
      <ul className="space-y-3">
        {problems.problems.map((problem, index) => (
          <Problem key={index} problem={problem} />
        ))}
      </ul>
    </section>
  );
}

function Problem({ problem }: { problem: SkillProblem }) {
  const t = useTranslations("skillImprovement.understand");
  const locale = useLocale();
  const agents = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    problem.agents.map((agent) => t("agent", { name: agent.name, runs: agent.runs })),
  );
  const example = problem.examples.find((item) => item.quote);
  return (
    <li className="space-y-1.5 rounded-xl border p-4">
      <p className="text-sm font-medium">{problem.title}</p>
      <p className="text-sm">{problem.summary}</p>
      <p className="text-muted-foreground text-xs">
        {t("occursIn", { agents, hidden: problem.hidden_agents, runs: problem.runs })}
      </p>
      {example?.quote && (
        <blockquote className="text-muted-foreground border-l-2 pl-3 text-xs">
          {example.quote}
        </blockquote>
      )}
      {problem.hidden_examples > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("hiddenExamples", { count: problem.hidden_examples })}
        </p>
      )}
    </li>
  );
}
