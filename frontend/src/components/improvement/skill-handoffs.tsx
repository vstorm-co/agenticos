"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useImprovementSkills } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { Improvement, ImprovementSkill } from "@/types/improvement";

/**
 * Problems the helper found in a skill, and newer skill versions the agent could move to.
 *
 * A skill is shared, so the agent's own changes never touch it: its problems are
 * handed to the skill's Improve, on the fork the agent follows or on main.
 */
export function SkillHandoffs({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.skills");
  const tErrors = useTranslations("errors");
  const { skills, error } = useImprovementSkills(session.agent_id, session.id);
  const shown = (skills?.items ?? []).filter((skill) => skill.problems.length || skill.update);
  if (!shown.length && !error) return null;
  return (
    <section className="space-y-3" data-tour="improvement-skill-handoffs">
      <h3 className="font-medium">{t("title")}</h3>
      {error ? (
        <p role="alert" className="text-destructive text-sm">
          {getErrorMessage(error, tErrors)}
        </p>
      ) : (
        <>
          <p className="text-muted-foreground text-sm">{t("intro")}</p>
          {shown.map((skill) => (
            <SkillCard key={skill.skill_id} skill={skill} sessionId={session.id} />
          ))}
        </>
      )}
    </section>
  );
}

function SkillCard({ skill, sessionId }: { skill: ImprovementSkill; sessionId: string }) {
  const t = useTranslations("improvement.skills");
  const fork = skill.binding?.fork;
  return (
    <article className="space-y-2 rounded-lg border p-4">
      <h4 className="font-medium">{skill.name}</h4>
      {skill.binding && skill.agents_on_line !== null && (
        <p className="text-muted-foreground text-sm">
          {fork
            ? t("forkLine", { fork: fork.name, count: skill.agents_on_line })
            : t("mainLine", { count: skill.agents_on_line })}
        </p>
      )}
      {skill.hidden_agents > 0 && (
        <p className="text-muted-foreground text-sm">
          {t("hidden", { count: skill.hidden_agents })}
        </p>
      )}
      {skill.problems.length > 0 && (
        <>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {skill.problems.map((problem) => (
              <li key={problem.problem}>
                {problem.problem}
                {problem.evidence.map(
                  (item) =>
                    item.quote && (
                      <q key={item.run_id} className="text-muted-foreground block">
                        {item.quote}
                      </q>
                    ),
                )}
              </li>
            ))}
          </ul>
          {skill.can_improve ? (
            <Button asChild size="sm">
              <Link href={ROUTES.SKILL_IMPROVE_FROM_RUN(skill.skill_id, sessionId)}>
                {fork
                  ? t("improveFork", { name: skill.name, fork: fork.name })
                  : t("improve", { name: skill.name })}
              </Link>
            </Button>
          ) : (
            <p className="text-muted-foreground text-sm">{t("askEditor", { name: skill.name })}</p>
          )}
        </>
      )}
      {skill.update && skill.binding && (
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span>{t("behind", { count: skill.binding.behind_main })}</span>
          <Button asChild size="sm" variant="outline">
            <Link href={ROUTES.SKILL_DETAIL(skill.skill_id)}>
              {skill.update.kind === "update_pinned"
                ? t("updatePinned", { version: skill.update.to_version })
                : t("catchUp")}
            </Link>
          </Button>
        </div>
      )}
    </article>
  );
}
