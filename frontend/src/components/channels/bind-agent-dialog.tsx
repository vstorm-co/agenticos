"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { AgentSelect } from "@/components/agents/agent-select";
import { ErrorState } from "@/components/states";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import type { Agent } from "@/types/agents";
import type { ChannelBot } from "@/types/channels";

interface BindAgentDialogProps {
  bot: ChannelBot;
  /** Agents the viewer may bind: publishable, not archived, not on a personal key. */
  agents: Agent[];
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  pending: boolean;
  onBind: (agent: Agent) => void;
  onClose: () => void;
}

/**
 * Choose the agent a bot answers as.
 *
 * The binding takes the agent's default environment; everything else about it
 * is changed on the agent's Availability tab. A refusal leaves the dialog open
 * so another agent can be chosen.
 */
export function BindAgentDialog({
  bot,
  agents,
  loading,
  error,
  onRetry,
  pending,
  onBind,
  onClose,
}: BindAgentDialogProps) {
  const t = useTranslations("pages.channels");
  const tErrors = useTranslations("errors");
  const common = useTranslations("common");
  const [agentId, setAgentId] = useState("");
  const chosen = agents.find((agent) => agent.id === agentId);
  const none = !loading && !error && agents.length === 0;

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("bindAgentTo", { bot: bot.name })}</DialogTitle>
          <DialogDescription>{t("bindAgentDescription")}</DialogDescription>
        </DialogHeader>
        {error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: common("retry"), onClick: onRetry }}
          />
        ) : none ? (
          <p className="text-muted-foreground text-sm">{t("noBindableAgents")}</p>
        ) : (
          <AgentSelect
            aria-label={t("bindAgentPlaceholder")}
            agents={agents}
            value={agentId}
            loading={loading}
            placeholder={t("bindAgentPlaceholder")}
            onChange={setAgentId}
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {common("cancel")}
          </Button>
          <Button disabled={!chosen || pending} onClick={() => chosen && onBind(chosen)}>
            {t("bindAgentConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
