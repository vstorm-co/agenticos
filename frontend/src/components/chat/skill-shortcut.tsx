"use client";

import { BookmarkPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAssistant } from "@/hooks/use-assistant";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import { Perm } from "@/types/permissions";

import { TURN_ACTION } from "./turn-action";

/** How much of the answer the Architect is handed when there is no conversation to read. */
const ANSWER_CHARS = 2000;

interface SkillShortcutProps {
  /** What the person asked for in this turn. */
  request: string;
  /** What the agent answered with. */
  answer: string;
  /** The conversation the turn is in, which the Architect reads whole. */
  conversationId?: string;
}

/**
 * "Make a skill of this" (#2301): the Architect is asked to write down how a
 * turn that worked was done, as a skill any agent can follow next time. Under
 * the answer, because the answer is what shows how. The Architect cannot see
 * this chat, so it is handed the conversation's id and reads all of it - the
 * steps and tool calls that made the answer, not only its last words - with
 * `read_conversation`; a turn not yet saved hands it the answer instead.
 */
export function SkillShortcut({ request, answer, conversationId }: SkillShortcutProps) {
  const t = useTranslations("chat.extras");
  const { can } = usePermissions();
  const { assistant } = useAssistant();
  const ask = useArchitectAskStore((state) => state.ask);
  if (assistant?.status !== "ready" || !assistant.can_use || !can(Perm.skillsEdit)) return null;

  const question = conversationId
    ? t("makeSkillFromConversation", { request, conversation: conversationId })
    : t("makeSkillAsk", { request, answer: answer.slice(0, ANSWER_CHARS) });
  return (
    <button
      type="button"
      onClick={() => ask(question)}
      title={t("makeSkill")}
      aria-label={t("makeSkill")}
      className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
    >
      <BookmarkPlus />
    </button>
  );
}
