"use client";

import { useState } from "react";
import { Bot, CalendarClock, Plug } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { Button } from "@/components/ui";
import { pointAt } from "@/lib/assistant-highlight";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import type { SetupKind, SetupProposal } from "@/lib/turn-extras";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";

/** Weekly on Monday at 8:00 UTC, for a routine proposed without a cadence. */
const WEEKLY = { schedule_kind: "cron", cron_expression: "0 8 * * 1" } as const;

const ICONS: Record<SetupKind, typeof Bot> = {
  agent: Bot,
  routine: CalendarClock,
  connection: Plug,
};

/**
 * What an agent proposed to set up - at the end of a welcome interview, most
 * often (#2301): each a card acted on in one click. A routine opens the routine
 * dialog filled in on the agent that proposed it, an agent is a question to the
 * Architect, and a connection opens the MCP servers page at its add button.
 */
export function SetupProposals({
  proposals,
  agentId,
}: {
  proposals: SetupProposal[];
  agentId: string | null;
}) {
  const t = useTranslations("chat.extras.setup");
  const router = useRouter();
  const ask = useArchitectAskStore((state) => state.ask);
  const [routine, setRoutine] = useState<TriggerTemplate | null>(null);

  const take = (proposal: SetupProposal) => {
    if (proposal.kind === "routine") {
      setRoutine({
        key: proposal.key,
        label: proposal.title,
        description: "",
        prompt: proposal.request,
        trigger_type: "schedule",
        suggested_cadence: proposal.cron
          ? { schedule_kind: "cron", cron_expression: proposal.cron }
          : WEEKLY,
      });
    } else if (proposal.kind === "agent") {
      ask(t("agentAsk", { request: proposal.request }));
    } else {
      router.push(ROUTES.MCP_SERVERS);
      void pointAt("mcp-add");
    }
  };

  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {proposals.map((proposal) => {
        const Icon = ICONS[proposal.kind];
        return (
          <div
            key={proposal.key}
            role="group"
            aria-label={proposal.title}
            className="bg-muted/60 flex flex-col gap-2 rounded-2xl p-3"
          >
            <span className="bg-card text-foreground shadow-card flex h-8 w-8 items-center justify-center rounded-xl">
              <Icon className="h-4 w-4" aria-hidden />
            </span>
            <p className="text-sm font-medium">{proposal.title}</p>
            <p className="text-muted-foreground flex-1 text-xs">{proposal.why}</p>
            <Button type="button" size="sm" variant="outline" onClick={() => take(proposal)}>
              {t(`take.${proposal.kind}`)}
            </Button>
          </div>
        );
      })}
      {routine && (
        <TriggerFormDialog
          agentId={agentId}
          open
          onOpenChange={(open) => !open && setRoutine(null)}
          initialTemplate={routine}
        />
      )}
    </div>
  );
}
