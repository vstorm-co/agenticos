"use client";

import { useTranslations } from "next-intl";
import { SectionCard } from "@/components/settings/settings-section";
import { Badge, Button } from "@/components/ui";
import { useLocalAgents } from "@/hooks/use-desktop";
import type { LocalAgent } from "@/lib/desktop/commands";

/**
 * Claude Code and Codex on this computer. Sign-in is each agent's own: the
 * button opens its command in Terminal, and no credential passes through here.
 */
export function LocalAgentSettings() {
  const t = useTranslations("desktop.settings.agents");
  const { state, signIn, signOut } = useLocalAgents();
  const error = state.error ?? signIn.error ?? signOut.error;
  return (
    <SectionCard title={t("title")} description={t("description")}>
      <ul className="space-y-3">
        {(state.data ?? []).map((agent) => (
          <li key={agent.id} className="flex items-center justify-between gap-3 text-sm">
            <span className="min-w-0">
              <span className="block truncate font-medium">{agent.name}</span>
              <span className="text-muted-foreground block truncate text-xs">
                {agent.installed
                  ? (agent.version ?? agent.path)
                  : t("installHint", { name: agent.name })}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-2">
              <Badge variant={agent.signed_in ? "default" : "outline"}>{label(t, agent)}</Badge>
              {agent.installed && agent.signed_in === true && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={signOut.isPending}
                  onClick={() => signOut.mutate(agent.id)}
                  aria-label={t("signOutNamed", { name: agent.name })}
                >
                  {t("signOut")}
                </Button>
              )}
              {agent.installed && agent.signed_in !== true && (
                <Button
                  size="sm"
                  disabled={signIn.isPending}
                  onClick={() => signIn.mutate(agent.id)}
                  aria-label={t("signInNamed", { name: agent.name })}
                >
                  {t("signIn")}
                </Button>
              )}
            </span>
          </li>
        ))}
      </ul>
      <p className="text-muted-foreground mt-3 text-xs">{t("terminalNote")}</p>
      {error && (
        <p role="alert" className="text-destructive mt-3 text-sm">
          {error.message}
        </p>
      )}
    </SectionCard>
  );
}

function label(t: ReturnType<typeof useTranslations>, agent: LocalAgent): string {
  if (!agent.installed) return t("notInstalled");
  if (agent.signed_in === true) return t("signedIn");
  if (agent.signed_in === false) return t("signedOut");
  return t("unknown");
}
