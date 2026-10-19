"use client";

import { Network } from "lucide-react";
import { useTranslations } from "next-intl";

import { CopyButton } from "@/components/chat/copy-button";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Switch } from "@/components/ui";
import { useAgent } from "@/hooks";
import type { Agent } from "@/types/agents";

/** Where the API serves an agent's A2A card and tasks - `app/api/routes/v1/a2a.py`. */
export function a2aAddresses(apiUrl: string, agentId: string): { card: string; endpoint: string } {
  const endpoint = `${apiUrl.replace(/\/$/, "")}/api/v1/a2a/${agentId}`;
  return { card: `${endpoint}/.well-known/agent-card.json`, endpoint };
}

/**
 * Whether other systems' agents may send this agent tasks over A2A (#2092).
 *
 * Off by default and only for a published agent, because what is served is the
 * published version. The two addresses are what somebody configuring the other
 * side needs; the card says the rest, including how to authenticate.
 */
export function A2aPanel({ agent, canManage }: { agent: Agent; canManage: boolean }) {
  const t = useTranslations("agents");
  const { apiUrl } = usePublicConfig();
  const { setA2a } = useAgent(agent.id);
  const published = agent.current_version_id !== null;
  const enabled = agent.a2a_enabled === true;
  const addresses = a2aAddresses(apiUrl, agent.id);

  return (
    <Card data-tour="agent-a2a">
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <CardTitle className="flex items-center gap-2">
              <Network className="text-muted-foreground size-4" aria-hidden />
              {t("a2aTitle")}
            </CardTitle>
            <CardDescription>{t("a2aDescription")}</CardDescription>
          </div>
          {canManage && (
            <Switch
              checked={enabled}
              disabled={!published || setA2a.isPending}
              aria-label={t("a2aSwitch")}
              onCheckedChange={(next) => setA2a.mutate(next)}
            />
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!published && <p className="text-muted-foreground text-xs">{t("a2aPublishFirst")}</p>}
        {enabled ? (
          <>
            <Address label={t("a2aCardUrl")} value={addresses.card} />
            <Address label={t("a2aEndpoint")} value={addresses.endpoint} />
            <p className="text-muted-foreground text-xs">{t("a2aAuthHint")}</p>
          </>
        ) : (
          published && <p className="text-muted-foreground text-xs">{t("a2aOff")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function Address({ label, value }: { label: string; value: string }) {
  return (
    <div className="group space-y-1">
      <p className="text-xs font-medium">{label}</p>
      <div className="bg-foreground/[0.04] flex items-center gap-2 rounded-md px-2.5 py-1.5">
        <code className="min-w-0 flex-1 truncate text-xs">{value}</code>
        <CopyButton text={value} className="opacity-100" />
      </div>
    </div>
  );
}
