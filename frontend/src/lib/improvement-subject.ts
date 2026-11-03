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

/**
 * Whether the reader may spend on the session. An agent's session says so in
 * `can_restart`, which the server sets from the reader's access to the agent. A
 * skill's sets `can_restart` only from whether Try again can start, and leaves
 * access to the page's edit check, so it never hides the step a session waits on.
 */
export function mayContinue(session: Pick<Improvement, "skill_id" | "can_restart">): boolean {
  return Boolean(session.skill_id) || session.can_restart !== false;
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
