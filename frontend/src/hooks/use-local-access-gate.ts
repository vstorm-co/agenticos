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
import type { ComputerAccessRequest } from "@/types/chat";

export function worksOnThisComputer(agent: Agent | undefined): agent is Agent {
  return agent !== undefined && (agent.local_workspace === true || !!agent.local_coding_agent);
}

const accountScope = () =>
  [useAuthStore.getState().user?.id, useOrgStore.getState().activeOrgId].join(":");

/**
 * Send with this agent's access to this computer when it has one that still holds:
 * the chat's own choice, or the one remembered for the agent. Never asks - an agent
 * asks for the computer when it needs it (`useComputerAccessOnUse`). Never inherits
 * another agent's default.
 */
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
        // Nothing granted that still holds: send without the computer. The agent
        // answers what needs no files, and asks for them when it reaches for them
        // - see `useComputerAccessOnUse`. A choice that no longer holds is not
        // sent along, or the run would be refused for it.
        if (explicit !== null) useWorkOnStore.getState().set(conversationId, null, false);
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

/** Ask where an agent may work on this computer, and remember the answer for it. */
export async function askForComputer(
  agent: Agent,
  conversationId: string | null,
  reason?: string,
  coding?: boolean,
): Promise<LocalTarget | null> {
  const owner = accountScope();
  const target = await useLocalAccessStore.getState().request({
    id: agent.id,
    name: agent.name,
    coding: coding ?? !!agent.local_coding_agent,
    reason,
  });
  if (
    target === null ||
    owner !== accountScope() ||
    useConversationStore.getState().currentConversationId !== conversationId
  )
    return null;
  const store = useWorkOnStore.getState();
  if (!target.computer_grant || target.computer_grant_agent === agent.id)
    store.rememberForAgent(agent.id, target);
  store.set(conversationId, target, false);
  return target;
}

/**
 * Answer a run that paused on `computer_access`: ask the person, remember their
 * choice for the agent and the chat, and release the run. The chat owns any
 * continuation so only the successful requesting turn can start it.
 *
 * Outside the desktop app there is no computer to grant, so the run is told at once.
 */
export function useComputerAccessOnUse({
  pending,
  respond,
  agent,
}: {
  pending: ComputerAccessRequest | null;
  respond: (granted: boolean) => void;
  agent: Agent | undefined;
}): void {
  const desktop = isDesktopShell(useShell());
  const t = useTranslations("chat.localAccess");
  const asked = useRef<ComputerAccessRequest | null>(null);
  useEffect(() => {
    if (pending === null || asked.current === pending) return;
    asked.current = pending;
    if (!desktop || !agent) {
      respond(false);
      return;
    }
    const conversationId = useConversationStore.getState().currentConversationId;
    askForComputer(agent, conversationId, pending.reason, pending.coding)
      .then((target) => {
        respond(target !== null);
      })
      .catch((error: unknown) => {
        reportShellFailure("asking for local access", error);
        toast.error(t("failed"));
        respond(false);
      });
  }, [pending, desktop, agent, respond, t]);
}
