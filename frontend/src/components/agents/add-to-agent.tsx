"use client";

import { useState } from "react";
import { Bot, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import { useAddToAgent, useAgents, usePermissions } from "@/hooks";
import type { AgentResourceRef } from "@/lib/agent-spec";
import { ROUTES } from "@/lib/constants";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useAddToAgentStore } from "@/stores";
import { Perm } from "@/types/permissions";

interface AddToAgentProps {
  resource: AgentResourceRef;
  /** What the resource is called, for the confirmation. */
  name: string;
  size?: "sm" | "default";
  className?: string;
}

/**
 * "Add to an agent", on a skill, a context file, a knowledge base or one of the
 * organization's MCP servers (#2075).
 *
 * Somebody who has just written a skill should not have to know that it is
 * bound in the Builder, under the Toolbox tab, inside the Skills capability's
 * panel. Two clicks here: open the list, pick the agent. The draft changes and
 * nothing is published, which the confirmation says, with the way to the
 * Builder. Not rendered for a caller who may not edit agents.
 */
export function AddToAgent({ resource, name, size = "sm", className }: AddToAgentProps) {
  const t = useTranslations("agents");
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);

  if (!can(Perm.agentsEdit)) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" size={size} className={cn("gap-1.5", className)}>
          <Plus className="h-3.5 w-3.5" />
          {t("addToAgent")}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-72 p-1">
        <p className="text-muted-foreground px-2 py-1.5 text-xs">{t("addToAgentHint")}</p>
        {open && <AgentChoices resource={resource} name={name} onDone={() => setOpen(false)} />}
      </PopoverContent>
    </Popover>
  );
}

/**
 * The agents a resource can be added to, and the adding (#2075).
 *
 * Shared by the button on a card and by the dialog the creation toast opens
 * (#2072), so both add the same way and confirm in the same words. Mounted only
 * while shown, so the agent list is fetched only when somebody looks.
 */
export function AgentChoices({
  resource,
  name,
  onDone,
}: {
  resource: AgentResourceRef;
  name: string;
  onDone: () => void;
}) {
  const t = useTranslations("agents");
  const router = useRouter();
  const { agents, isLoading } = useAgents();
  const add = useAddToAgent();

  const pick = async (agentId: string, agentName: string) => {
    // A refusal is toasted by the mutation; the list stays open to pick another.
    const result = await add.mutateAsync({ agentId, resource }).catch(() => null);
    if (result === null) return;
    const { already } = result;
    onDone();
    const toBuilder = {
      label: t("openInBuilder"),
      onClick: () => router.push(ROUTES.AGENT_DETAIL(agentId)),
    };
    if (already) toast.info(t("alreadyOnAgent", { name, agent: agentName }), { action: toBuilder });
    else toast.success(t("addedToAgent", { name, agent: agentName }), { action: toBuilder });
  };

  return (
    <div className="max-h-72 overflow-y-auto">
      {isLoading ? (
        <p className="text-muted-foreground px-2 py-3 text-sm">{t("loadingAgents")}</p>
      ) : agents.length === 0 ? (
        <div className="space-y-2 px-2 py-3 text-sm">
          <p className="text-muted-foreground">{t("noAgentToAddTo")}</p>
          <Button size="sm" variant="outline" onClick={() => router.push(ROUTES.AGENTS)}>
            <Bot className="h-3.5 w-3.5" />
            {t("createAnAgent")}
          </Button>
        </div>
      ) : (
        agents.map((agent) => (
          <button
            key={agent.id}
            type="button"
            disabled={add.isPending}
            onClick={() => pick(agent.id, agent.name)}
            className="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm disabled:opacity-50"
          >
            <AgentAvatar
              agentId={agent.id}
              slug={agent.slug}
              hasAvatar={agent.has_avatar}
              colorSlot={agent.avatar_color}
              size="sm"
            />
            <span className="truncate">{agent.name}</span>
          </button>
        ))
      )}
    </div>
  );
}

/**
 * The dialog the creation toast's "Add to an agent" opens (#2072), mounted once
 * in the layout and driven by `useAddToAgentStore`.
 */
export function AddToAgentPrompt() {
  const t = useTranslations("agents");
  const offer = useAddToAgentStore((state) => state.offer);
  const close = useAddToAgentStore((state) => state.close);

  return (
    <Dialog open={offer !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent className={DIALOG_CONFIRM}>
        {offer !== null && (
          <>
            <DialogHeader>
              <DialogTitle>{t("addNamedToAgent", { name: offer.name })}</DialogTitle>
              <DialogDescription>{t("addToAgentHint")}</DialogDescription>
            </DialogHeader>
            <AgentChoices resource={offer.resource} name={offer.name} onDone={close} />
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
