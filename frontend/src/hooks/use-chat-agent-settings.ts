"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { useAgent } from "@/hooks/use-agents";
import { useRemoteDraft } from "@/hooks/use-remote-draft";
import { getErrorMessage } from "@/lib/api-error";
import type { AgentSpec } from "@/types/agents";

/** One identified agent's draft, kept mounted when its workspace pane is collapsed. */
export function useChatAgentSettings(agentId: string, readOnly: boolean) {
  const detail = useAgent(agentId);
  const tErrors = useTranslations("errors");
  const [spec, setSpec] = useState<AgentSpec | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const agent = detail.agent;
  if (agent?.id === agentId && spec === null) setSpec(agent.draft_spec);
  const remote = useRemoteDraft({
    resource: "agent",
    id: agentId,
    local: spec,
    stored: agent?.draft_spec,
    fetchedAt: detail.fetchedAt,
    adopt: setSpec,
  });
  // Resource authority also enables Restore elsewhere; this pane offers only
  // standalone, active configuration.
  const editable =
    !readOnly &&
    !detail.error &&
    agent?.can_edit === true &&
    !agent.workflow_id &&
    agent.status !== "archived";
  const dirty = spec !== null && JSON.stringify(spec) !== JSON.stringify(agent?.draft_spec);
  const blocked = !editable || detail.saveDraft.isPending || remote.held || !spec?.name.trim();

  const save = async (): Promise<boolean> => {
    if (blocked || spec === null) return false;
    setFailure(null);
    try {
      // The hook instance is keyed by account, organization and agent. Its mutation
      // closes over this agent ID even when the visible chat switches during the request.
      await detail.saveDraft.mutateAsync(spec);
      return true;
    } catch (error) {
      setFailure(getErrorMessage(error, tErrors));
      return false;
    }
  };

  return {
    ...detail,
    spec,
    remote,
    dirty,
    blocked,
    editable,
    failure,
    save,
    update: (patch: Partial<AgentSpec>) => {
      if (!editable || detail.saveDraft.isPending) return;
      setFailure(null);
      setSpec((current) => (current ? { ...current, ...patch } : current));
    },
    reset: () => {
      if (detail.saveDraft.isPending) return;
      setFailure(null);
      setSpec(agent?.draft_spec ?? null);
    },
  };
}
