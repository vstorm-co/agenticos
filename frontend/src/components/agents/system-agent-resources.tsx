"use client";

import { useTranslations } from "next-intl";

import { CapabilityResources, type AgentResources } from "@/components/agents/capability-resources";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { CONTEXT_ID, SKILLS_ID } from "@/lib/agent-spec";
import type { CapabilityBindingSpec } from "@/types/agents";

/**
 * The standing text a system agent knows: its context files and its skills.
 *
 * Its page has no Toolbox, where an ordinary agent picks them in the panel of the
 * capability that reads each. These are those panels' own pickers, and the page
 * writes a pick the way the Toolbox does: the capability is bound with the first
 * file or skill and dropped with the last, so there is no switch to forget here.
 */
export function SystemAgentResources({
  capabilities,
  resources,
  disabled,
}: {
  capabilities: CapabilityBindingSpec[];
  resources: AgentResources;
  disabled: boolean;
}) {
  const t = useTranslations("agents");
  const bound = (id: string) =>
    capabilities.some((binding) => binding.id === id && binding.enabled);

  return (
    <Card>
      {/* The header, not the card: the galleries under it can run past the
          bottom of the screen, and a spotlight on all of it lights nothing. */}
      <CardHeader data-tour="agent-system-resources">
        <CardTitle>{t("systemAgentResources")}</CardTitle>
        <CardDescription>{t("systemAgentResourcesHelp")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <section className="space-y-3">
          <h3 className="text-sm font-medium">{t("contextFilesHeading")}</h3>
          <CapabilityResources
            capabilityId={CONTEXT_ID}
            enabled={bound(CONTEXT_ID)}
            resources={resources}
            disabled={disabled}
          />
        </section>
        <section className="space-y-3">
          <h3 className="text-sm font-medium">{t("skillsHeading")}</h3>
          <CapabilityResources
            capabilityId={SKILLS_ID}
            enabled={bound(SKILLS_ID)}
            resources={resources}
            disabled={disabled}
          />
        </section>
      </CardContent>
    </Card>
  );
}
