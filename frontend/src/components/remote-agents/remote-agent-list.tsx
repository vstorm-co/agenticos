"use client";

import { useState } from "react";
import { KeyRound, Network, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";

import { Badge, ConfirmDialog, IconButton } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { ExternalAgent } from "@/types/external-agents";

/** The host a remote agent answers on - what a reader checks it against. */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * The registered remote agents, each as its card described it.
 *
 * The skills are shown because they are what a delegating agent reads before it
 * hands one work, and the host because it is where that work goes. Refresh and
 * Remove only on a registration the server says this person may change.
 */
export function RemoteAgentList({
  agents,
  onRefresh,
  onRemove,
}: {
  agents: ExternalAgent[];
  onRefresh: (id: string) => Promise<ExternalAgent>;
  onRemove: (id: string) => Promise<void>;
}) {
  const t = useTranslations("remoteAgents");
  const tErrors = useTranslations("errors");
  const [removing, setRemoving] = useState<ExternalAgent | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async (agent: ExternalAgent) => {
    setBusy(agent.id);
    try {
      await onRefresh(agent.id);
      toast.success(t("refreshed", { name: agent.name }));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <ul className="divide-border divide-y">
        {agents.map((agent) => (
          <li key={agent.id} className="flex items-start gap-3 px-5 py-4">
            <span className="bg-foreground/[0.06] mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg">
              <Network className="text-muted-foreground size-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{agent.name}</span>
                <span className="text-muted-foreground font-mono text-xs">{agent.slug}</span>
                {agent.secret_id !== null && (
                  <Badge variant="outline" className="gap-1">
                    <KeyRound className="size-3" aria-hidden />
                    {t("withKey")}
                  </Badge>
                )}
              </div>
              {agent.description && (
                <p className="text-muted-foreground text-sm">{agent.description}</p>
              )}
              <p className="text-muted-foreground text-xs">
                {t("answersOn", { host: hostOf(agent.endpoint_url) })}
              </p>
              {agent.skills.length > 0 && (
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {agent.skills.map((skill) => (
                    <span
                      key={skill.id}
                      title={skill.description}
                      className="bg-foreground/[0.06] rounded-full px-2 py-0.5 text-xs"
                    >
                      {skill.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
            {agent.can_manage && (
              <div className="flex shrink-0 items-center">
                <IconButton
                  aria-label={t("refreshNamed", { name: agent.name })}
                  title={t("refresh")}
                  disabled={busy === agent.id}
                  onClick={() => void refresh(agent)}
                >
                  <RefreshCw className="size-4" />
                </IconButton>
                <IconButton
                  aria-label={t("removeNamed", { name: agent.name })}
                  title={t("remove")}
                  onClick={() => setRemoving(agent)}
                >
                  <Trash2 className="size-4" />
                </IconButton>
              </div>
            )}
          </li>
        ))}
      </ul>
      {removing !== null && (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setRemoving(null)}
          title={t("removeTitle", { name: removing.name })}
          description={t("removeDescription")}
          confirmLabel={t("remove")}
          destructive
          onConfirm={async () => {
            try {
              await onRemove(removing.id);
            } catch (error) {
              toast.error(getErrorMessage(error, tErrors));
            }
            setRemoving(null);
          }}
        />
      )}
    </>
  );
}
