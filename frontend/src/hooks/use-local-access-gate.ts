"use client";

import { useCallback, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useShell } from "@/hooks/use-shell";
import { getLocalState, type LocalTarget } from "@/lib/desktop/commands";
import { isDesktopShell, reportShellFailure } from "@/lib/desktop/shell";
import { useConversationStore } from "@/stores";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { useLocalAccessStore } from "@/stores/local-access-store";
import { useWorkOnStore } from "@/stores/work-on-store";
import type { Agent } from "@/types/agents";

export function worksOnThisComputer(agent: Agent | undefined): agent is Agent {
  return agent !== undefined && (agent.local_workspace === true || !!agent.local_coding_agent);
}

const accountScope = () =>
  [useAuthStore.getState().user?.id, useOrgStore.getState().activeOrgId].join(":");

/** Send only after resolving this agent's access, without inheriting another agent's default. */
export function useLocalAccessGate<A extends unknown[]>(
  send: (...args: A) => unknown,
  agent: Agent | undefined,
  options?: { selectedAgentId: string | null; metadataPending: boolean; projectId?: string | null },
): (...args: A) => void {
  const desktop = isDesktopShell(useShell());
  const t = useTranslations("chat.localAccess");
  const latest = useRef(agent);
  useEffect(() => {
    latest.current = agent;
  }, [agent]);
  const { selectedAgentId, metadataPending, projectId } = options ?? {};
  const pending = useRef<
    { agentId: string; conversationId: string | null; scope: string; args: A }[]
  >([]);
  const gate = useCallback(
    (...args: A) => {
      if (desktop && agent === undefined && selectedAgentId) {
        if (metadataPending)
          pending.current.push({
            agentId: selectedAgentId,
            conversationId: useConversationStore.getState().currentConversationId,
            scope: accountScope(),
            args,
          });
        else toast.error(t("agentUnavailable"));
        return;
      }
      if (!desktop || !worksOnThisComputer(agent)) {
        send(...args);
        return;
      }
      const conversationId = useConversationStore.getState().currentConversationId;
      const scope = accountScope();
      const stillHere = () =>
        scope === accountScope() &&
        latest.current?.id === agent.id &&
        useConversationStore.getState().currentConversationId === conversationId;
      const workOn = useWorkOnStore.getState();
      const explicit = workOn.explicitTargetFor(conversationId);
      // A project's cloud workspace supersedes the agent's local default.
      const project =
        projectId ??
        (conversationId === null ? useConversationStore.getState().pendingProjectId : null);
      if (project && explicit === null) {
        send(...args);
        return;
      }
      void (async () => {
        const allowed = async (target: LocalTarget | null, remembered: boolean) => {
          if (target === null) return false;
          if (target.computer_grant_agent && target.computer_grant_agent !== agent.id) return false;
          // Older apps grant one conversation only; never reuse their consent in another chat.
          if (remembered && target.computer_grant && target.computer_grant_agent !== agent.id)
            return false;
          const native = await getLocalState();
          if (target.computer_grant)
            return native.computer_grants?.includes(target.computer_grant) ?? !remembered;
          return native.grants.some(
            (grant) => grant.path === target.folder && grant.mode === target.mode,
          );
        };
        if (await allowed(explicit, false)) {
          if (stillHere()) send(...args);
          return;
        }
        const remembered = workOn.agentTargetFor(agent.id);
        if (await allowed(remembered, true)) {
          if (stillHere()) {
            useWorkOnStore.getState().set(conversationId, remembered, false);
            send(...args);
          }
          return;
        }
        if (!stillHere()) return;
        const target = await useLocalAccessStore
          .getState()
          .request({ id: agent.id, name: agent.name, coding: !!agent.local_coding_agent });
        if (target === null || !stillHere()) return;
        const store = useWorkOnStore.getState();
        if (!target.computer_grant || target.computer_grant_agent === agent.id)
          store.rememberForAgent(agent.id, target);
        store.set(conversationId, target, false);
        send(...args);
      })().catch((error: unknown) => {
        reportShellFailure("checking local access", error);
        if (stillHere()) toast.error(t("failed"));
      });
    },
    [desktop, agent, send, selectedAgentId, metadataPending, projectId, t],
  );
  useEffect(() => {
    if (metadataPending || pending.current.length === 0) return;
    const queued = pending.current;
    pending.current = [];
    for (const item of queued)
      if (
        item.agentId === agent?.id &&
        item.conversationId === useConversationStore.getState().currentConversationId &&
        item.scope === accountScope()
      )
        gate(...item.args);
      else toast.error(t("agentUnavailable"));
  }, [agent, gate, metadataPending, t]);
  return gate;
}
