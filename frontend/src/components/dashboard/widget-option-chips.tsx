"use client";

import { useTranslations } from "next-intl";

import { useAgents, useMembers } from "@/hooks";
import type { WidgetOptions } from "@/lib/dashboard/layouts";
import { useOrgStore } from "@/stores";

/**
 * What a card overrides, said in its own header.
 *
 * Not decoration and not a nicety: the page carries one time filter and one
 * organization, so a card answering about ninety days - or about one agent -
 * while everything beside it answers about thirty and all of them is a wrong
 * number unless the card says otherwise where the number is read. The chips are
 * therefore rendered from the *stored* options rather than from anything the
 * widget did with them.
 *
 * A style is not a chip. It changes how the same answer is drawn, not which
 * answer it is, and a reader can see it.
 */
export function WidgetOptionChips({ options }: { options?: WidgetOptions }) {
  const t = useTranslations("dashboard");
  if (!options?.period && !options?.agentId && !options?.userId) return null;

  return (
    <span className="flex min-w-0 shrink items-center gap-1">
      {options.period ? <Chip>{t(`period.${options.period}`)}</Chip> : null}
      {options.agentId ? <AgentChip agentId={options.agentId} /> : null}
      {options.userId ? <PersonChip userId={options.userId} /> : null}
    </span>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="bg-muted text-muted-foreground max-w-32 truncate rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap">
      {children}
    </span>
  );
}

/**
 * The agent's name, from the catalog the page already holds - a chip reading
 * `a1f3-…` names nothing. An id the caller can no longer see (deleted, or
 * shared and then unshared) falls back to the generic word rather than to a
 * blank chip: the card *is* still narrowed, and hiding that is the one thing
 * these chips exist to prevent.
 */
function AgentChip({ agentId }: { agentId: string }) {
  const t = useTranslations("dashboard");
  const { agents } = useAgents();
  const agent = agents.find((candidate) => candidate.id === agentId);
  return <Chip>{agent?.name ?? t("options.oneAgent")}</Chip>;
}

function PersonChip({ userId }: { userId: string }) {
  const t = useTranslations("dashboard");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { members } = useMembers(activeOrgId ?? "");
  const member = members.find((candidate) => candidate.user_id === userId);
  return <Chip>{member?.full_name || member?.email || t("options.onePerson")}</Chip>;
}
