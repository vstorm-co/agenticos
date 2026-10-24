"use client";

import { useState } from "react";
import { BookmarkCheck, BookmarkX, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { askForCapability, enableCapability } from "@/lib/capability-requests-api";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import {
  capabilityCardsOf,
  memoryChangesOf,
  setupProposalsOf,
  type CapabilityCard,
} from "@/lib/turn-extras";
import type { ChatMessage } from "@/types/chat";
import { Perm } from "@/types/permissions";

import { SetupProposals } from "./setup-proposals";

interface TurnExtrasProps {
  message: ChatMessage;
  /** The agent that answered, by name, for the card's sentence. */
  agentName?: string;
}

/**
 * What a turn's calls left under its answer (#2301): what the agent noted about
 * the person, a card for a capability it lacked, and things to set up. Its next
 * steps sit above the composer instead - see `NextSteps`.
 */
export function TurnExtras({ message, agentName }: TurnExtrasProps) {
  if (message.role !== "assistant" || message.isStreaming) return null;
  const changes = memoryChangesOf(message.toolCalls);
  const cards = capabilityCardsOf(message.toolCalls);
  const proposals = setupProposalsOf(message.toolCalls);
  if (!changes.length && !cards.length && !proposals.length) return null;
  return (
    <div className="mt-1 space-y-2">
      {changes.length > 0 && <MemoryLine labels={changes} />}
      {cards.map((card) => (
        <CapabilityRequestCard key={card.callId} card={card} agentName={agentName} />
      ))}
      {proposals.length > 0 && (
        <SetupProposals proposals={proposals} agentId={message.agentId ?? null} />
      )}
    </div>
  );
}

function MemoryLine({ labels }: { labels: ReturnType<typeof memoryChangesOf> }) {
  const t = useTranslations("chat.extras");
  const router = useRouter();
  return (
    <ul className="text-muted-foreground space-y-0.5 text-xs">
      {labels.map((change) => (
        <li key={change.callId} className="flex items-center gap-1.5">
          {change.forgot ? (
            <BookmarkX className="h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            <BookmarkCheck className="h-3.5 w-3.5 shrink-0" aria-hidden />
          )}
          <span className="truncate">
            {change.forgot
              ? t("forgot", { note: change.label })
              : t("remembered", { note: change.label })}
          </span>
          <button
            type="button"
            onClick={() => router.push(ROUTES.SETTINGS_MEMORY)}
            className="text-foreground shrink-0 font-medium underline-offset-2 hover:underline"
          >
            {t("manageMemory")}
          </button>
        </li>
      ))}
    </ul>
  );
}

type CardState = "idle" | "busy" | "enabled" | "drafted" | "asked";

function CapabilityRequestCard({ card, agentName }: { card: CapabilityCard; agentName?: string }) {
  const t = useTranslations("chat.extras");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const [state, setState] = useState<CardState>("idle");
  // Only a hint for the label: a scoped `agents:edit` may not reach this agent,
  // and an explicit grant may reach it without the permission. The server decides
  // on the agent itself, so the switch is always tried and a refusal asks the owner.
  const editor = can(Perm.agentsEdit);

  async function act() {
    setState("busy");
    try {
      const done = await enableCapability(card.agentId, card.capabilityId).catch(
        (error: unknown) => {
          if (error instanceof ApiError && error.status === 403) return null;
          throw error;
        },
      );
      if (done) {
        setState(done.published ? "enabled" : "drafted");
      } else {
        await askForCapability(card.agentId, card.capabilityId, card.reason);
        setState("asked");
      }
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
      setState("idle");
    }
  }

  const outcome =
    state === "enabled"
      ? t("capabilityOn", { name: card.name })
      : state === "drafted"
        ? t("capabilityDrafted", { name: card.name })
        : state === "asked"
          ? t("capabilityAsked")
          : null;

  return (
    <div role="group" className="bg-muted/60 flex items-start gap-3 rounded-2xl p-3">
      <span className="bg-card text-foreground shadow-card flex h-8 w-8 shrink-0 items-center justify-center rounded-xl">
        <Sparkles className="h-4 w-4" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-sm">
          {t("capabilityNeeded", { agent: agentName ?? t("thisAgent"), name: card.name })}
          <span className="text-muted-foreground block text-xs">{card.reason}</span>
        </p>
        {outcome ? (
          <p className="text-muted-foreground text-xs" role="status">
            {outcome}
          </p>
        ) : (
          <Button type="button" size="sm" disabled={state === "busy"} onClick={act}>
            {editor ? t("switchOn", { name: card.name }) : t("askOwner")}
          </Button>
        )}
      </div>
    </div>
  );
}
