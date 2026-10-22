"use client";

import { BookmarkPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAssistant } from "@/hooks/use-assistant";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import { Perm } from "@/types/permissions";

import { TURN_ACTION } from "./turn-action";

/** How much of the answer the Architect is handed: enough to see how it was done. */
const ANSWER_CHARS = 2000;

interface SkillShortcutProps {
  /** What the person asked for in this turn. */
  request: string;
  /** What the agent answered with. */
  answer: string;
}

/**
 * "Make a skill of this" (#2301): the Architect is asked to write down how a
 * turn that worked was done, as a skill any agent can follow next time. Under
 * the answer, because the answer is what shows how - and the Architect, which
 * cannot see this conversation, is handed both halves.
 */
export function SkillShortcut({ request, answer }: SkillShortcutProps) {
  const t = useTranslations("chat.extras");
  const { can } = usePermissions();
  const { assistant } = useAssistant();
  const ask = useArchitectAskStore((state) => state.ask);
  if (assistant?.status !== "ready" || !assistant.can_use || !can(Perm.skillsEdit)) return null;

  return (
    <button
      type="button"
      onClick={() => ask(t("makeSkillAsk", { request, answer: answer.slice(0, ANSWER_CHARS) }))}
      title={t("makeSkill")}
      aria-label={t("makeSkill")}
      className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
    >
      <BookmarkPlus />
    </button>
  );
}
