/** What a side of an eval is called on screen: "v7", "Draft", "v2 + 1 suggestion". */

import type { ArmRole, ArmSource, ProposalCheckRecord } from "@/types/eval-runs";

type Translate = (
  key: string,
  values?: { version?: number; count?: number; agent?: string; fork?: string },
) => string;

/**
 * A proposal's check, with the name of the agent it ran on once the page has read it
 * and, for a skill's check, the stored version its proposal is weighed against.
 */
export type SideCheck = ProposalCheckRecord & {
  agent?: string;
  current?: { number: number; fork_name: string | null } | null;
};

/**
 * A side by what it ran - a published version by its number, otherwise its source.
 * A stage of a skill's check names its sides by the text each read, since the
 * page says once which agent the stage ran on.
 *
 * The candidate of a check of the authoring assistant's proposal is named by what
 * it adds to the side it is measured against, so both names say what differs. A
 * skill's check runs one agent on the skill as it is and as proposed, so both sides
 * are that agent, named by which skill each one read.
 */
export function sideName(
  side: { version_number: number | null; source: ArmSource; role?: ArmRole },
  t: Translate,
  check?: SideCheck | null,
): string {
  if (check?.kind === "skill" && check.skill_check_id && side.role !== undefined) {
    if (side.role === "candidate") return t("checkStage.proposed");
    const current = check.current;
    if (!current) return t("checkStage.current");
    return current.fork_name === null
      ? t("checkStage.currentVersion", { version: current.number })
      : t("checkStage.currentFork", { fork: current.fork_name, version: current.number });
  }
  if (check?.kind === "skill" && check.agent !== undefined && side.role !== undefined) {
    if (side.role === "candidate") return t("skillProposed", { agent: check.agent });
    const current = check.current;
    if (!current) return t("skillCurrent", { agent: check.agent });
    return current.fork_name === null
      ? t("skillCurrentVersion", { agent: check.agent, version: current.number })
      : t("skillCurrentFork", {
          agent: check.agent,
          fork: current.fork_name,
          version: current.number,
        });
  }
  if (check && side.role === "candidate") return proposedName(check, t);
  if (side.version_number !== null) return t("version", { version: side.version_number });
  return side.source === "explicit" ? t("proposed") : t("draft");
}

function proposedName(check: ProposalCheckRecord, t: Translate): string {
  // Null only for an agent never published, whose suggestions are measured on the draft.
  const version = check.base_version ?? undefined;
  if (check.kind !== "agent") {
    return t(check.kind === "skill" ? "proposedSkill" : "proposedContext", { version });
  }
  if (check.on_draft) return t("draftPlus", { count: check.suggestions });
  return t("versionPlus", { version, count: check.suggestions });
}
