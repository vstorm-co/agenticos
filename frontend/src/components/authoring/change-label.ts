"use client";

import { useTranslations } from "next-intl";

import type { Hunk } from "@/types/authoring";
import { fieldLabel } from "./field-change";

/** A field that tunes how the agent runs rather than what it reaches. */
const SETTING = /^(model_settings\/|max_steps$|description$)/;

/**
 * What kind of change a suggestion is, in the words the Improve wizard uses:
 * "Instructions", "Tool description: search", "New skill", "Model",
 * "Setting: Temperature", "Add knowledge base Policies".
 */
export function useChangeLabel(): (hunk: Hunk) => string {
  const tKind = useTranslations("improvement.changeKind");
  const tField = useTranslations("authoring.field");
  const t = useTranslations("authoring.tabs");
  return (hunk) => {
    if (hunk.kind === "instructions") return tKind("instructions");
    if (hunk.kind === "tool_override") {
      return tKind("tool", { tool: hunk.base_name ?? hunk.tool_id ?? "" });
    }
    if (hunk.kind === "create_skill") return tKind("skill");
    const field = fieldLabel(hunk, tField);
    return SETTING.test(String(hunk.path)) ? t("setting", { field }) : field;
  };
}
