"use client";

import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { useAgentVersion, useCapabilityCatalog, useMcpCatalog, useMcpConnections } from "@/hooks";
import { useCapabilityGuide } from "@/hooks/use-capability-guide";
import { capabilityRows, connectedAppNames } from "@/lib/agent-capabilities";
import type { Agent } from "@/types/agents";

/**
 * What the selected agent can do, in the empty chat, before anyone types.
 *
 * Generated from the agent's own bindings, never hand-written per agent: the
 * published version's enabled capabilities, in the plain words the capability
 * guide gives each one, with the guide's first example as something to try;
 * and the connected apps its published version is bound to, by name. It sits
 * in the empty state rather than the Builder because that is where the
 * question "which agent do I talk to?" is asked - a person choosing an agent
 * should not have to open the Builder to learn what one does.
 *
 * An agent with no bindings says so plainly, so the panel never invents a
 * capability. It says nothing at all while any list it reads from is still
 * loading, or where a lookup failed and left it with no rows for an agent
 * that is bound to something: a "no tools" line drawn on a failed catalog
 * would be a lie about a capable agent.
 */
export function AgentCapabilitiesPanel({
  agent,
  onPick,
}: {
  agent: Agent | undefined;
  onPick: (prompt: string) => void;
}) {
  const t = useTranslations("chat.empty");
  const { capabilities, isLoading: catalogLoading } = useCapabilityCatalog();
  const guide = useCapabilityGuide();
  const { version, isLoading: versionLoading } = useAgentVersion(
    agent?.id ?? null,
    agent?.current_version_id ?? null,
  );
  const { connections, isLoading: connectionsLoading } = useMcpConnections();
  const { servers, isLoading: serversLoading } = useMcpCatalog();

  if (!agent || catalogLoading || versionLoading || connectionsLoading || serversLoading) {
    return null;
  }
  const rows = capabilityRows(agent.published_capabilities, capabilities, guide);
  const apps = connectedAppNames(version?.spec.mcp_servers, connections, servers);
  if (rows.length === 0 && apps.length === 0) {
    const bound =
      (agent.published_capabilities ?? []).length > 0 ||
      (version?.spec.mcp_servers ?? []).length > 0;
    if (bound) return null;
    return (
      <section aria-label={t("panelTitle")} className="mx-auto mt-8 w-full">
        <h3 className="text-foreground text-sm font-medium">{t("panelTitle")}</h3>
        <p className="text-muted-foreground mt-2 text-sm leading-relaxed">{t("panelEmpty")}</p>
      </section>
    );
  }
  return (
    <section aria-label={t("panelTitle")} className="mx-auto mt-8 w-full">
      <h3 className="text-foreground text-sm font-medium">{t("panelTitle")}</h3>
      <ul className="mt-3 space-y-4">
        {rows.map((row) => {
          const example = row.example;
          return (
            <li key={row.id}>
              <p className="text-sm leading-relaxed">
                <span className="text-foreground font-medium">{row.name}</span>
                <span className="text-muted-foreground"> — {row.does}</span>
              </p>
              {example !== null && (
                <button
                  type="button"
                  onClick={() => onPick(example)}
                  className="hover:bg-muted focus-visible:ring-ring bg-muted/60 text-foreground/80 mt-1.5 inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-left text-[13px] transition-colors outline-none focus-visible:ring-2"
                >
                  <ArrowUpRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
                  {example}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      {apps.length > 0 && (
        <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
          {t("panelApps", { apps: apps.join(" · ") })}
        </p>
      )}
    </section>
  );
}
