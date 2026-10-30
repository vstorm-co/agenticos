"use client";
import { useCallback, useEffect, useRef } from "react";
import { useVoiceReadiness } from "@/hooks/use-voice-readiness";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { usePermissions } from "@/hooks/use-permissions";
import { useAgents } from "@/hooks/use-agents";
import { useChatStore, useConversationStore } from "@/stores";
import { VoiceCallButton } from "@/components/voice/voice-call-button";
import {
  VoiceCallBar,
  VoiceCallFeed,
  callActive,
  showVoiceApproval,
} from "@/components/voice/voice-call-view";
import { Perm } from "@/types/permissions";
import { AGENT_CALLS_ANCHOR } from "@/components/agents/voice-card";
import { reportShellFailure } from "@/lib/desktop/shell";
import type { VoiceSavedTurn } from "@/types/voice";

export function QuickAskVoice({
  agentId,
  conversationId,
  active,
  disabled,
  onConversation,
  onActiveChange,
}: {
  agentId: string | null;
  conversationId: string | null;
  active: boolean;
  disabled: boolean;
  onConversation: (id: string) => void;
  onActiveChange: (active: boolean) => void;
}) {
  const { readiness, failed } = useVoiceReadiness(active ? agentId : null);
  const { agents } = useAgents();
  const agent = agents.find((item) => item.id === agentId);
  const { can } = usePermissions();
  const canDecide = can(Perm.approvalsDecide);
  const add = useChatStore((s) => s.addMessage);
  const messages = useChatStore((s) => s.messages);
  const setConversation = useConversationStore((s) => s.setCurrentConversationId);
  const currentAgent = useRef(agentId);
  const callAgent = useRef(agentId);
  const onSaved = useCallback(
    (turn: VoiceSavedTurn) => {
      if (turn.role !== "assistant" && turn.role !== "user") {
        reportShellFailure("unexpected Quick Ask voice role", new Error(turn.role));
        return;
      }
      add({
        id: turn.id,
        role: turn.role,
        content: turn.content,
        timestamp: new Date(),
        agentId: turn.role === "assistant" ? (callAgent.current ?? undefined) : undefined,
      });
    },
    [add],
  );
  const opened = useCallback(
    (id: string) => {
      setConversation(id);
      onConversation(id);
    },
    [setConversation, onConversation],
  );
  const session = useVoiceSession({ onConversation: opened, onTurnSaved: onSaved });
  const live = callActive(session);
  useEffect(() => {
    onActiveChange(live);
  }, [live, onActiveChange]);
  const end = session.end;
  useEffect(() => {
    if (!active || currentAgent.current !== agentId) end();
    currentAgent.current = agentId;
  }, [active, agentId, end]);
  const start = () => {
    if (!active || disabled || !agentId || !readiness?.available || !readiness.transport) return;
    callAgent.current = agentId;
    void session.start({
      kind: "console",
      agentId,
      conversationId,
      transport: readiness.transport,
    });
  };
  const hidden = new Set(messages.map((message) => message.id));
  return (
    <div className="border-border border-t px-3 py-2">
      {live ? (
        <VoiceCallBar
          session={session}
          agentName={agent?.name ?? ""}
          canDecide={canDecide}
          onShowApproval={showVoiceApproval}
        />
      ) : (
        <VoiceCallButton
          readiness={readiness}
          failed={failed}
          disabled={disabled || !active}
          onStart={start}
          setUpHref={
            agentId && can(Perm.agentsEdit) ? `/agents/${agentId}#${AGENT_CALLS_ANCHOR}` : null
          }
        />
      )}
      {session.call.phase !== "idle" && (
        <div className="max-h-52 overflow-y-auto text-sm">
          <VoiceCallFeed
            session={session}
            agentName={agent?.name ?? ""}
            agent={agent}
            canDecide={canDecide}
            hidden={hidden}
            onCallAgain={start}
            onContinueInText={end}
          />
        </div>
      )}
    </div>
  );
}
