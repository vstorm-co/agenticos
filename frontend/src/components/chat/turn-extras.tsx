"use client";

import { useState } from "react";
import { ArrowUpRight, BookmarkCheck, BookmarkX, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { askForCapability, enableCapability } from "@/lib/capability-requests-api";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import {
  capabilityCardsOf,
  followUpsOf,
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
  /** Set on the latest answer only: older next steps are history, not offers. */
  onFollowUp?: (step: string) => void;
}

/**
 * What a turn's calls left under its answer (#2301): what the agent noted about
 * the person, a card for a capability it lacked, things to set up, and next
 * steps as buttons.
 */
export function TurnExtras({ message, agentName, onFollowUp }: TurnExtrasProps) {
  if (message.role !== "assistant" || message.isStreaming) return null;
  const changes = memoryChangesOf(message.toolCalls);
  const cards = capabilityCardsOf(message.toolCalls);
  const proposals = setupProposalsOf(message.toolCalls);
  const steps = onFollowUp ? followUpsOf(message.toolCalls) : [];
  if (!changes.length && !cards.length && !proposals.length && !steps.length) return null;
  return (
    <div className="space-y-2 pb-3">
      {changes.length > 0 && <MemoryLine labels={changes} />}
      {cards.map((card) => (
        <CapabilityRequestCard key={card.callId} card={card} agentName={agentName} />
      ))}
      {proposals.length > 0 && (
        <SetupProposals proposals={proposals} agentId={message.agentId ?? null} />
      )}
      {steps.length > 0 && onFollowUp && <FollowUpButtons steps={steps} onPick={onFollowUp} />}
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
  const editor = can(Perm.agentsEdit);

  async function act() {
    setState("busy");
    try {
      if (editor) {
        const done = await enableCapability(card.agentId, card.capabilityId);
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

function FollowUpButtons({ steps, onPick }: { steps: string[]; onPick: (step: string) => void }) {
  const t = useTranslations("chat.extras");
  return (
    <div role="group" aria-label={t("nextSteps")} className="flex flex-wrap gap-1.5">
      {steps.map((step) => (
        <button
          key={step}
          type="button"
          onClick={() => onPick(step)}
          className="group bg-muted/60 hover:bg-muted focus-visible:ring-ring text-foreground inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] transition-colors outline-none focus-visible:ring-2"
        >
          {step}
          <ArrowUpRight className="text-muted-foreground group-hover:text-foreground h-3.5 w-3.5" />
        </button>
      ))}
    </div>
  );
}
