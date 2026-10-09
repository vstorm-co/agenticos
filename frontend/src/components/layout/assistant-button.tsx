"use client";

import { Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { useAgents, usePermissions } from "@/hooks";
import { useAgentTemplates } from "@/hooks/use-agent-templates";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { Perm } from "@/types/permissions";

/** The shipped template the assistant is installed from, and the slug it gets. */
export const ASSISTANT_TEMPLATE = "general/platform-assistant";
export const ASSISTANT_SLUG = "platform-assistant";

/**
 * The Platform Assistant, one click from every page (#1798).
 *
 * The assistant is an ordinary agent installed from a template and bound to the
 * `platform` capability, so it lives in the chat like any other - streaming,
 * runs, cost and the approval cards its writes wait on. This button opens a new
 * conversation with it, or, until it is published, says what is missing and who
 * can fix it.
 */
export function AssistantButton() {
  const t = useTranslations("assistant");
  const router = useRouter();
  const { can } = usePermissions();
  const { agents } = useAgents();
  const select = useAgentSelectionStore((state) => state.select);
  const setConversation = useConversationStore((state) => state.setCurrentConversationId);
  const { install, isInstalling } = useAgentTemplates(false, (result) =>
    router.push(`${ROUTES.AGENTS}/${result.agent_id}`),
  );
  const assistant = agents.find((agent) => agent.slug === ASSISTANT_SLUG);
  const canBuild = can(Perm.agentsEdit);

  const open = (agentId: string) => {
    select(agentId);
    setConversation(null);
    router.push(ROUTES.CHAT);
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("title")}
          data-tour="assistant-button"
          className="text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors outline-none focus-visible:ring-1"
        >
          <Sparkles className="h-[1.1rem] w-[1.1rem] shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent side="right" align="end" className="w-72 space-y-3">
        <div className="space-y-1">
          <p className="text-foreground text-sm font-semibold">{t("title")}</p>
          <p className="text-muted-foreground text-xs">{t("why")}</p>
        </div>
        {assistant?.status === "published" ? (
          <Button size="sm" className="w-full" onClick={() => open(assistant.id)}>
            {t("open")}
          </Button>
        ) : assistant && canBuild ? (
          <>
            <p className="text-muted-foreground text-xs">{t("draftWhy")}</p>
            <Button
              size="sm"
              className="w-full"
              onClick={() => router.push(`${ROUTES.AGENTS}/${assistant.id}`)}
            >
              {t("finish")}
            </Button>
          </>
        ) : canBuild ? (
          <Button
            size="sm"
            className="w-full"
            disabled={isInstalling}
            onClick={() => install(ASSISTANT_TEMPLATE)}
          >
            {t("setUp")}
          </Button>
        ) : (
          <p className="text-muted-foreground text-xs">{t("askAdmin")}</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
