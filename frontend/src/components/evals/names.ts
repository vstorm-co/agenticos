/** What a side of an eval is called on screen: "v7", "Draft", "Proposed changes". */

import type { ArmSource } from "@/types/eval-runs";

type Translate = (key: string, values?: { version: number }) => string;

/** A side by what it ran - a published version by its number, otherwise its source. */
export function sideName(
  side: { version_number: number | null; source: ArmSource },
  t: Translate,
): string {
  if (side.version_number !== null) return t("version", { version: side.version_number });
  return side.source === "explicit" ? t("proposed") : t("draft");
}
