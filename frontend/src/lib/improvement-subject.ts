/**
 * Whose improvement sessions these are: an agent's, by its id, or a skill's.
 *
 * Both answer the same routes under their own root, so a step the two share is
 * written once and reaches the right one through `subjectOf`.
 */

import type { Improvement } from "@/types/improvement";

export type ImprovementSubject = string | { skillId: string };

/** The subject a session improves. */
export function subjectOf(session: Pick<Improvement, "agent_id" | "skill_id">): ImprovementSubject {
  return session.skill_id ? { skillId: session.skill_id } : session.agent_id;
}

export function improvementsRoot(subject: ImprovementSubject): string {
  return typeof subject === "string"
    ? `/agents/${subject}/improvements`
    : `/skills/${subject.skillId}/improvements`;
}

/** An agent's sessions keep the cache keys they always had; a skill's get their own. */
export function subjectKey(subject: ImprovementSubject): string {
  return typeof subject === "string" ? subject : `skill:${subject.skillId}`;
}
