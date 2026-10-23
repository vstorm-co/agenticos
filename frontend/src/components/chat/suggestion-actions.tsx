"use client";

import { useState } from "react";
import { Bot, CalendarClock, Package, Radar, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { useMcpCatalog } from "@/hooks";
import { useSuggestions } from "@/hooks/use-suggestions";
import { getErrorMessage } from "@/lib/api-error";
import type { Suggestion, SuggestionKind } from "@/lib/suggestions-api";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";

/** Weekly on Monday at 8:00 UTC, for a repeated request the night gave no cadence. */
const WEEKLY = { schedule_kind: "cron", cron_expression: "0 8 * * 1" } as const;

const ICONS: Record<SuggestionKind, typeof Bot> = {
  routine: CalendarClock,
  agent: Bot,
  profile: UserRound,
  role_pack: Package,
  finding: Radar,
};

export const payloadText = (value: unknown): string => (typeof value === "string" ? value : "");

/** What cannot wait leads, whatever order it arrived in. */
export const urgentFirst = (items: Suggestion[]): Suggestion[] =>
  [...items].sort((a, b) => Number(b.urgent === true) - Number(a.urgent === true));

/**
 * Taking or declining what the platform proposed (#2301), the same wherever it
 * is shown. A routine opens the routine dialog filled in - `dialog` is where it
 * renders - an agent is a question to the Architect, a profile update and a role
 * pack are saved by the server, and a watch's finding is marked done.
 */
export function useSuggestionActions(agentId: string | null) {
  const t = useTranslations("chat.suggestions");
  const tErrors = useTranslations("errors");
  const { accept, dismiss } = useSuggestions();
  const ask = useArchitectAskStore((state) => state.ask);
  const [routine, setRoutine] = useState<{
    suggestionId: string;
    template: TriggerTemplate;
  } | null>(null);

  const decide = async (work: () => Promise<unknown>) => {
    try {
      await work();
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };

  const take = (suggestion: Suggestion) =>
    decide(async () => {
      if (suggestion.kind === "routine") {
        // Taken once the routine exists (the dialog's `onCreated`): a dialog
        // closed or refused leaves the card to try again.
        const cron = payloadText(suggestion.payload.cron);
        setRoutine({
          suggestionId: suggestion.id,
          template: {
            key: `suggestion-${suggestion.id}`,
            label: suggestion.title,
            description: "",
            prompt: payloadText(suggestion.payload.prompt),
            trigger_type: "schedule",
            suggested_cadence: cron ? { schedule_kind: "cron", cron_expression: cron } : WEEKLY,
          },
        });
        return;
      }
      if (suggestion.kind === "agent") {
        ask(t("agentAsk", { request: payloadText(suggestion.payload.request) }));
      }
      await accept(suggestion.id);
      if (suggestion.kind === "profile") {
        const user = useAuthStore.getState().user;
        if (user) useAuthStore.getState().setUser({ ...user, ...suggestion.payload });
        toast.success(t("profileSaved"));
      } else if (suggestion.kind === "role_pack") {
        toast.success(t("packInstalling"));
      }
    });

  const notNow = (suggestion: Suggestion) => decide(() => dismiss(suggestion.id));

  const dialog = routine && (
    <TriggerFormDialog
      agentId={agentId}
      open
      onOpenChange={(open) => !open && setRoutine(null)}
      initialTemplate={routine.template}
      onCreated={() => void decide(() => accept(routine.suggestionId))}
    />
  );
  return { take, notNow, dialog };
}

/** Where a suggestion came from: the watched server's mark for a finding, the kind's icon otherwise. */
export function useSuggestionSource() {
  const { servers } = useMcpCatalog();
  return (suggestion: Suggestion) =>
    suggestion.kind === "finding"
      ? servers.find((entry) => entry.key === payloadText(suggestion.payload.server))
      : undefined;
}

export function SuggestionMark({
  suggestion,
  className,
}: {
  suggestion: Suggestion;
  className?: string;
}) {
  const server = useSuggestionSource()(suggestion);
  const Icon = ICONS[suggestion.kind];
  return (
    <span
      className={cn(
        "bg-card text-foreground shadow-card flex h-8 w-8 shrink-0 items-center justify-center rounded-xl",
        className,
      )}
    >
      {server ? (
        <McpServerIcon icon={server.icon} name={server.name} url={server.url} className="h-4 w-4" />
      ) : (
        <Icon className="h-4 w-4" aria-hidden />
      )}
    </span>
  );
}
