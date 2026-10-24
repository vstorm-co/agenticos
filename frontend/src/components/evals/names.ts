/** What a side of an eval is called on screen: "v7", "Draft", "v2 + 1 suggestion". */

import type { ArmRole, ArmSource, ProposalCheckRecord } from "@/types/eval-runs";

type Translate = (key: string, values?: { version?: number; count?: number }) => string;

/**
 * A side by what it ran - a published version by its number, otherwise its source.
 *
 * The candidate of a check of the authoring assistant's proposal is named by what
 * it adds to the side it is measured against, so both names say what differs.
 */
export function sideName(
  side: { version_number: number | null; source: ArmSource; role?: ArmRole },
  t: Translate,
  check?: ProposalCheckRecord | null,
): string {
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
