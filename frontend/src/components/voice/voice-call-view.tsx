"use client";

import { Wrench } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Spinner } from "@/components/ui";
import { ThinkingOrb } from "@/components/ui/thinking-orb";
import type { VoiceSession } from "@/hooks/use-voice-session";
import { toolCaption } from "@/lib/agent-step-captions";
import { glideOrJump } from "@/lib/motion";
import { viewState } from "@/lib/voice/call-reducer";
import type { Agent } from "@/types/agents";

import { callActive, useSecondClock } from "./voice-call-bar";
import {
  VoiceApprovalCard,
  VoiceApprovalSettled,
  VoiceApprovalUnavailable,
} from "./voice-approval-card";
import { VoiceCallSummary } from "./voice-call-summary";
import { VoiceCaptions } from "./voice-captions";

export { callActive, VoiceCallBar } from "./voice-call-bar";

/**
 * Bring the approval waiting on the call into view and put focus on Approve -
 * the call bar strip's "Show card", for a person who scrolled up meanwhile.
 */
export function showVoiceApproval(): void {
  const card = document.querySelector<HTMLElement>("[data-voice-approval]");
  card?.scrollIntoView?.({ block: "center", behavior: glideOrJump() });
  card?.querySelector<HTMLElement>("[data-voice-approve]")?.focus({ preventScroll: true });
}

/** A row in the agent's column of the conversation, under its avatar's gutter. */
function AgentRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex gap-2 py-2 sm:gap-4">
      <div className="w-8 shrink-0 sm:w-9" />
      <div className="max-w-[85%] min-w-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * The call, in the conversation (#54) - the half of the call view that is not
 * the bar. Turns arrive as ordinary messages with the live caption inside
 * them; while the agent thinks or runs a tool it says so where its answer will
 * be; an approval appears as a card with the exact arguments, and stays as the
 * record once decided; and the call's end lands as a summary card. Saved turns
 * reach the conversation itself, and `hidden` - the turns it already holds -
 * keeps each from being drawn twice.
 */
export function VoiceCallFeed({
  session,
  agentName,
  agent,
  canDecide,
  hidden,
  onCallAgain,
  onContinueInText,
}: {
  session: VoiceSession;
  agentName: string;
  agent?: Agent;
  canDecide: boolean;
  hidden: ReadonlySet<string>;
  onCallAgain: () => void;
  /** End the call to carry on in text; the page decides where focus goes. */
  onContinueInText: () => void;
}) {
  const t = useTranslations("chat");
  const tTools = useTranslations("chat.tools");
  const { call } = session;
  const { approval } = call;
  const now = useSecondClock(approval !== null);
  if (call.phase === "idle") return null;
  const live = callActive(session);
  const view = viewState(call);
  return (
    <div data-testid="voice-call-feed">
      <VoiceCaptions
        captions={call.captions}
        agentName={agentName}
        agent={agent}
        hidden={hidden}
        speaking={live}
      />
      {live && view === "thinking" && (
        <AgentRow>
          <span
            role="status"
            className="bg-foreground/[0.04] inline-flex items-center gap-1.5 rounded-full py-1 pr-3.5 pl-1.5"
          >
            <ThinkingOrb state="breathing" size={20} className="h-7 w-7" />
            <span className="text-muted-foreground text-xs">{t("thinking")}</span>
          </span>
        </AgentRow>
      )}
      {live && view === "tool" && call.tool !== null && (
        <AgentRow>
          <div
            aria-busy="true"
            className="bg-card flex items-center gap-2.5 rounded-xl border px-3 py-2 text-[13px]"
          >
            <span className="bg-muted text-muted-foreground grid h-[26px] w-[26px] shrink-0 place-items-center rounded-lg">
              <Wrench className="h-3.5 w-3.5" aria-hidden />
            </span>
            <span className="min-w-0 flex-1">
              <span className="voice-call-shimmer font-medium">
                {toolCaption(call.tool, tTools)}
              </span>{" "}
              <code className="bg-muted rounded px-1 font-mono text-[11.5px]">{call.tool}</code>
            </span>
            <Spinner className="text-muted-foreground h-3.5 w-3.5" />
          </div>
        </AgentRow>
      )}
      {call.settled && (
        <AgentRow>
          <VoiceApprovalSettled settled={call.settled} />
        </AgentRow>
      )}
      {approval && (
        <AgentRow>
          <VoiceApprovalCard
            approval={approval}
            now={now}
            canDecide={canDecide}
            onDecide={(approve) => session.decide(approval.id, approve)}
          />
        </AgentRow>
      )}
      {live && call.approvalUnavailable && (
        <AgentRow>
          <VoiceApprovalUnavailable
            tool={call.approvalUnavailable.tool}
            args={call.approvalUnavailable.args}
            onDismiss={session.dismissUnavailable}
            onEndCall={onContinueInText}
          />
        </AgentRow>
      )}
      {/* There from the call's start, so the summary landing in it is announced. */}
      <div role="status" aria-live="polite" data-testid="voice-call-end">
        <VoiceCallSummary call={call} agentName={agentName} onCallAgain={onCallAgain} />
      </div>
    </div>
  );
}
